from __future__ import annotations

import asyncio
import json
import re
import time
from contextlib import suppress
from datetime import date
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import HttpUrl, ValidationError

from profileproof.errors import (
    InvalidProfileUrl,
    ProfileNotFound,
    ProviderRejected,
    ProviderUnavailable,
    RateLimitExceeded,
)
from profileproof.models import (
    Certification,
    DateRange,
    Education,
    Experience,
    Language,
    ProfileData,
    ProfileImages,
    ProviderName,
)
from profileproof.rate_limit import SlidingWindowLimiter
from profileproof.url_policy import CanonicalProfileUrl, canonicalize_linkedin_profile_url

from .base import ProviderContext, ProviderResult


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    item = _mapping(value)
    text = item.get("text")
    return text.strip() if isinstance(text, str) and text.strip() else None


def _public_text(value: object) -> str | None:
    text = _text(value)
    if text is None or all(character in {"*", " ", "\t", "\r", "\n"} for character in text):
        return None
    return text


def _date(value: object) -> date | None:
    item = _mapping(value)
    year = item.get("year")
    if not isinstance(year, int):
        return None
    raw_month = item.get("month")
    raw_day = item.get("day")
    month: int = raw_month if isinstance(raw_month, int) else 1
    day: int = raw_day if isinstance(raw_day, int) else 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _public_date(value: object) -> date | None:
    if isinstance(value, int):
        try:
            return date(value, 1, 1)
        except ValueError:
            return None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", value.strip())
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2) or 1), int(match.group(3) or 1))
    except ValueError:
        return None


def _public_period(value: object) -> DateRange:
    item = _mapping(value)
    start = _public_date(item.get("startDate"))
    end = _public_date(item.get("endDate"))
    return DateRange(start=start, end=end, is_current=start is not None and end is None)


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capturing = False
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value for name, value in attrs}
        if tag.casefold() == "script" and (attributes.get("type") or "").casefold() == (
            "application/ld+json"
        ):
            self._capturing = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._capturing:
            self.blocks.append("".join(self._parts))
            self._capturing = False
            self._parts = []


def _public_person(document: str) -> dict[str, Any]:
    parser = _JsonLdParser()
    parser.feed(document)
    for block in parser.blocks:
        try:
            value = json.loads(unescape(block))
        except (TypeError, ValueError):
            continue
        roots = value if isinstance(value, list) else [value]
        for root in roots:
            item = _mapping(root)
            graph = item.get("@graph")
            candidates = graph if isinstance(graph, list) else [item]
            for candidate in candidates:
                person = _mapping(candidate)
                if person.get("@type") == "Person":
                    return person
    return {}


def _public_values(value: object) -> list[object]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def _public_profile(person: dict[str, Any]) -> ProfileData:
    address = _mapping(person.get("address"))
    location = _public_text(address.get("addressLocality"))
    country = _public_text(address.get("addressCountry"))
    if country and location and country.casefold() not in location.casefold():
        location = f"{location}, {country}"
    elif location is None:
        location = country

    titles = [
        title
        for value in _public_values(person.get("jobTitle"))
        if (title := _public_text(value)) is not None
    ]
    experience: list[Experience] = []
    for index, value in enumerate(_public_values(person.get("worksFor"))):
        organization = _mapping(value)
        role = _mapping(organization.get("member"))
        company = _public_text(organization.get("name"))
        title = (
            _public_text(role.get("roleName"))
            or _public_text(role.get("jobTitle"))
            or (titles[index] if index < len(titles) else None)
        )
        if company:
            experience.append(
                Experience(
                    title=title,
                    company=company,
                    location=_public_text(organization.get("location")),
                    description=_public_text(role.get("description")),
                    dates=_public_period(role),
                )
            )

    education: list[Education] = []
    for value in _public_values(person.get("alumniOf")):
        organization = _mapping(value)
        membership = _mapping(organization.get("member"))
        school = _public_text(organization.get("name"))
        if school:
            education.append(
                Education(
                    school=school,
                    degree=_public_text(membership.get("roleName")),
                    description=_public_text(membership.get("description")),
                    dates=_public_period(membership),
                )
            )

    languages = [
        Language(name=name)
        for value in _public_values(person.get("knowsLanguage"))
        if (name := _public_text(_mapping(value).get("name") if isinstance(value, dict) else value))
        is not None
    ]
    skills = [
        skill
        for value in _public_values(person.get("knowsAbout") or person.get("skills"))
        if (
            skill := _public_text(_mapping(value).get("name") if isinstance(value, dict) else value)
        )
        is not None
    ]
    image = _mapping(person.get("image"))
    profile_image: HttpUrl | None = None
    image_url = _public_text(image.get("contentUrl") or person.get("image"))
    if image_url:
        with suppress(ValidationError):
            profile_image = HttpUrl(image_url)
    return ProfileData(
        name=_public_text(person.get("name")),
        headline=" · ".join(titles) or None,
        location=location,
        about=_public_text(person.get("disambiguatingDescription")),
        experience=experience,
        education=education,
        skills=skills,
        languages=languages,
        images=ProfileImages(profile=profile_image),
    )


def _period(value: object) -> DateRange:
    period = _mapping(value)
    start = _date(period.get("start") or period.get("startDate"))
    end = _date(period.get("end") or period.get("endDate"))
    return DateRange(start=start, end=end, is_current=start is not None and end is None)


def _types(payload: dict[str, Any], suffix: str) -> list[dict[str, Any]]:
    included = payload.get("included")
    if not isinstance(included, list):
        return []
    return [
        item
        for item in included
        if isinstance(item, dict) and str(item.get("$type", "")).endswith(suffix)
    ]


def _image(value: object) -> HttpUrl | None:
    vector = _mapping(value)
    for key in ("vectorImage", "displayImageReference", "displayImage"):
        nested = vector.get(key)
        if isinstance(nested, dict):
            resolved = _image(nested)
            if resolved is not None:
                return resolved
    root = _text(vector.get("rootUrl"))
    artifacts = vector.get("artifacts")
    if root is None or not isinstance(artifacts, list):
        return None
    valid = [item for item in artifacts if isinstance(item, dict)]
    if not valid:
        return None
    largest = max(valid, key=lambda item: int(item.get("width", 0)) * int(item.get("height", 0)))
    segment = _text(largest.get("fileIdentifyingUrlPathSegment"))
    if segment is None:
        return None
    try:
        return HttpUrl(f"{root}{segment}")
    except ValidationError:
        return None


def _index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    included = payload.get("included")
    if not isinstance(included, list):
        return {}
    return {
        urn: item
        for item in included
        if isinstance(item, dict) and (urn := _text(item.get("entityUrn"))) is not None
    }


def _profile_entity(payload: dict[str, Any], public_identifier: str) -> dict[str, Any]:
    index = _index(payload)
    data = _mapping(payload.get("data"))
    elements = data.get("*elements")
    if isinstance(elements, list) and elements:
        target = index.get(str(elements[0]))
        if target is not None:
            return target
    for profile in _types(payload, ".Profile"):
        identifier = _text(profile.get("publicIdentifier"))
        if identifier and identifier.casefold() == public_identifier.casefold():
            return profile
    return {}


def _collection(payload: dict[str, Any], reference: object) -> list[dict[str, Any]]:
    index = _index(payload)
    collection = index.get(str(reference), {})
    elements = collection.get("*elements")
    if not isinstance(elements, list):
        return []
    return [index[urn] for urn in elements if isinstance(urn, str) and urn in index]


def _profile_records(
    payload: dict[str, Any], profile: dict[str, Any], reference: str, suffix: str
) -> list[dict[str, Any]]:
    records = _collection(payload, profile.get(reference))
    return [record for record in records if str(record.get("$type", "")).endswith(suffix)]


def _location(payload: dict[str, Any], profile: dict[str, Any]) -> str | None:
    direct = _text(profile.get("locationName")) or _text(profile.get("location"))
    if direct is not None:
        return direct
    geo_urn = _text(_mapping(profile.get("geoLocation")).get("geoUrn"))
    geo = _index(payload).get(geo_urn or "", {})
    return _text(geo.get("defaultLocalizedName")) or _text(geo.get("localizedName"))


def _experiences(payload: dict[str, Any], profile: dict[str, Any]) -> list[Experience]:
    result: list[Experience] = []
    positions: list[dict[str, Any]] = []
    for group in _collection(payload, profile.get("*profilePositionGroups")):
        positions.extend(_collection(payload, group.get("*profilePositionInPositionGroup")))
    if not positions:
        profile_id = _text(profile.get("entityUrn"))
        bare_id = profile_id.rsplit(":", 1)[-1] if profile_id else None
        positions = [
            item
            for item in _types(payload, ".Position")
            if bare_id and bare_id in str(item.get("entityUrn", ""))
        ]
    for item in positions:
        title = _text(item.get("title"))
        company = _text(item.get("companyName"))
        if title and company:
            result.append(
                Experience(
                    title=title,
                    company=company,
                    location=_text(item.get("locationName")),
                    description=_text(item.get("description")),
                    employment_type=_text(item.get("employmentType"))
                    or _text(item.get("employmentTypeUrn")),
                    dates=_period(item.get("dateRange") or item.get("timePeriod")),
                )
            )
    return result


def _education(payload: dict[str, Any], profile: dict[str, Any]) -> list[Education]:
    result: list[Education] = []
    for item in _profile_records(payload, profile, "*profileEducations", ".Education"):
        school = _text(item.get("schoolName"))
        if school:
            result.append(
                Education(
                    school=school,
                    degree=_text(item.get("degreeName")),
                    field_of_study=_text(item.get("fieldOfStudy")),
                    description=_text(item.get("description")),
                    dates=_period(item.get("dateRange") or item.get("timePeriod")),
                )
            )
    return result


def _certifications(payload: dict[str, Any], profile: dict[str, Any]) -> list[Certification]:
    result: list[Certification] = []
    for item in _profile_records(payload, profile, "*profileCertifications", ".Certification"):
        name = _text(item.get("name"))
        if name is None:
            continue
        period = _mapping(item.get("dateRange") or item.get("timePeriod"))
        result.append(
            Certification(
                name=name,
                issuer=_text(item.get("authority")),
                issued=_date(period.get("start") or period.get("startDate")),
                expires=_date(period.get("end") or period.get("endDate")),
                credential_id=_text(item.get("licenseNumber")),
            )
        )
    return result


class LinkedInSessionProvider:
    name = ProviderName.LINKEDIN_DIRECT
    endpoint = "https://www.linkedin.com/voyager/api/identity/dash/profiles"
    public_endpoint = "https://www.linkedin.com/in/{public_identifier}"

    def __init__(
        self,
        client: httpx.AsyncClient,
        li_at: str | None,
        jsessionid: str | None,
        calls_per_day: int,
        min_interval_seconds: float,
        user_agent: str,
    ) -> None:
        self._client = client
        self._li_at = li_at
        self._jsessionid = jsessionid
        self._quota = SlidingWindowLimiter(calls_per_day, 86_400)
        self._min_interval_seconds = min_interval_seconds
        self._user_agent = user_agent
        self._request_lock = asyncio.Lock()
        self._last_request_started = 0.0

    @property
    def configured(self) -> bool:
        return True

    @property
    def authenticated(self) -> bool:
        return bool(self._li_at and self._jsessionid)

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        async with self._request_lock:
            delay = self._last_request_started + self._min_interval_seconds - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request_started = time.monotonic()
            return await self._client.get(url, **kwargs)

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult:
        del context
        allowed, _, retry_after = await self._quota.allow("linkedin-session")
        if not allowed:
            raise RateLimitExceeded(
                f"The LinkedIn daily safety quota is exhausted; retry in {retry_after}s."
            )
        if not self.authenticated:
            return await self._fetch_public(profile_url)
        try:
            return await self._fetch_authenticated(profile_url)
        except (ProfileNotFound, ProviderUnavailable):
            return await self._fetch_public(profile_url)

    async def _fetch_authenticated(self, profile_url: CanonicalProfileUrl) -> ProviderResult:
        csrf = str(self._jsessionid).strip('"')
        try:
            response = await self._get(
                self.endpoint,
                params={
                    "q": "memberIdentity",
                    "memberIdentity": quote(profile_url.public_identifier, safe=""),
                    "decorationId": (
                        "com.linkedin.voyager.dash.deco.identity.profile."
                        "FullProfileWithEntities-101"
                    ),
                },
                headers={
                    "Accept": "application/vnd.linkedin.normalized+json+2.1",
                    "Accept-Language": "en-US,en;q=0.9",
                    "csrf-token": csrf,
                    "Referer": (
                        "https://www.linkedin.com/in/"
                        f"{quote(profile_url.public_identifier, safe='')}/"
                    ),
                    "User-Agent": self._user_agent,
                    "x-li-lang": "en_US",
                    "x-restli-protocol-version": "2.0.0",
                    "Cookie": f'li_at={self._li_at}; JSESSIONID="{csrf}"',
                },
            )
        except httpx.HTTPError as error:
            raise ProviderRejected("LinkedIn could not be reached.") from error
        if response.status_code == 404:
            raise ProfileNotFound("LinkedIn did not return that profile.")
        if response.status_code in {302, 401, 403}:
            raise ProviderUnavailable("The LinkedIn session is expired or was rejected.")
        if response.status_code in {429, 999}:
            raise RateLimitExceeded("LinkedIn rate-limited this deployment.")
        if response.status_code != 200:
            raise ProviderRejected(f"LinkedIn returned HTTP {response.status_code}.")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise ProviderRejected("LinkedIn returned invalid JSON.") from error
        entity = _profile_entity(payload, profile_url.public_identifier)
        if not entity:
            raise ProfileNotFound("LinkedIn did not return that profile.")
        returned_identifier = _text(entity.get("publicIdentifier"))
        if (
            returned_identifier
            and returned_identifier.casefold() != profile_url.public_identifier.casefold()
        ):
            raise ProviderRejected("LinkedIn returned a different profile identity.")
        first_name = _text(entity.get("firstName"))
        last_name = _text(entity.get("lastName"))
        profile_name = " ".join(value for value in (first_name, last_name) if value) or None
        picture = _mapping(entity.get("profilePicture"))
        background = _mapping(entity.get("backgroundPicture"))
        skills = [
            name
            for item in _profile_records(payload, entity, "*profileSkills", ".Skill")
            if (name := _text(item.get("name"))) is not None
        ]
        languages = [
            Language(name=name, proficiency=_text(item.get("proficiency")))
            for item in _profile_records(payload, entity, "*profileLanguages", ".Language")
            if (name := _text(item.get("name"))) is not None
        ]
        profile = ProfileData(
            name=profile_name,
            headline=_text(entity.get("headline")),
            location=_location(payload, entity),
            about=_text(entity.get("summary")),
            experience=_experiences(payload, entity),
            education=_education(payload, entity),
            skills=skills,
            certifications=_certifications(payload, entity),
            languages=languages,
            images=ProfileImages(
                profile=_image(picture),
                background=_image(background),
            ),
        )
        return ProviderResult(
            profile=profile,
            mode="authenticated_linkedin_voyager",
            consented=True,
            limitations=[
                "Data reflects fields visible to the configured LinkedIn account.",
                "LinkedIn may change this undocumented response without notice.",
            ],
            warnings=["authenticated_session", "undocumented_upstream"],
        )

    async def _fetch_public(self, profile_url: CanonicalProfileUrl) -> ProviderResult:
        endpoint = self.public_endpoint.format(
            public_identifier=quote(profile_url.public_identifier, safe="")
        )
        try:
            response = await self._get(
                endpoint,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": self._user_agent,
                },
            )
        except httpx.HTTPError as error:
            raise ProviderRejected("LinkedIn could not be reached.") from error
        if response.status_code == 404:
            raise ProfileNotFound("LinkedIn did not return that profile.")
        if response.status_code in {302, 401, 403}:
            raise ProviderUnavailable("LinkedIn did not expose a public profile response.")
        if response.status_code in {429, 999}:
            raise RateLimitExceeded("LinkedIn rate-limited this deployment.")
        if response.status_code != 200:
            raise ProviderRejected(f"LinkedIn returned HTTP {response.status_code}.")
        if len(response.content) > 2_000_000:
            raise ProviderRejected("LinkedIn returned an unexpectedly large profile response.")
        person = _public_person(response.text)
        if not person:
            raise ProfileNotFound("LinkedIn did not expose structured public profile data.")
        identity = _public_text(person.get("url")) or _public_text(person.get("sameAs"))
        if identity:
            try:
                returned = canonicalize_linkedin_profile_url(identity)
            except InvalidProfileUrl:
                raise ProviderRejected("LinkedIn returned an invalid profile identity.") from None
            if returned.public_identifier.casefold() != profile_url.public_identifier.casefold():
                raise ProviderRejected("LinkedIn returned a different profile identity.")
        profile = _public_profile(person)
        if profile.name is None:
            raise ProfileNotFound("LinkedIn redacted the public profile identity.")
        return ProviderResult(
            profile=profile,
            mode="public_linkedin_jsonld",
            consented=False,
            limitations=[
                "Data is limited to fields LinkedIn exposes in its public server-rendered profile.",
                "LinkedIn may redact or omit experience, skills, certifications, and languages.",
                "LinkedIn may change this undocumented response without notice.",
            ],
            warnings=["public_profile", "partial_public_view", "undocumented_upstream"],
        )
