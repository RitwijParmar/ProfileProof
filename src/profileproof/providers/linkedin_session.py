from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import HttpUrl, ValidationError

from profileproof.errors import (
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
from profileproof.url_policy import CanonicalProfileUrl

from .base import ProviderContext, ProviderResult


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


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


def _period(value: object) -> DateRange:
    period = _mapping(value)
    start = _date(period.get("startDate"))
    end = _date(period.get("endDate"))
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


def _profile_entity(payload: dict[str, Any]) -> dict[str, Any]:
    profiles = _types(payload, ".Profile")
    return profiles[0] if profiles else _mapping(payload.get("data"))


def _experiences(payload: dict[str, Any]) -> list[Experience]:
    result: list[Experience] = []
    for item in _types(payload, ".Position"):
        title = _text(item.get("title"))
        company = _text(item.get("companyName"))
        if title and company:
            result.append(
                Experience(
                    title=title,
                    company=company,
                    location=_text(item.get("locationName")),
                    description=_text(item.get("description")),
                    employment_type=_text(item.get("employmentType")),
                    dates=_period(item.get("timePeriod")),
                )
            )
    return result


def _education(payload: dict[str, Any]) -> list[Education]:
    result: list[Education] = []
    for item in _types(payload, ".Education"):
        school = _text(item.get("schoolName"))
        if school:
            result.append(
                Education(
                    school=school,
                    degree=_text(item.get("degreeName")),
                    field_of_study=_text(item.get("fieldOfStudy")),
                    description=_text(item.get("description")),
                    dates=_period(item.get("timePeriod")),
                )
            )
    return result


def _certifications(payload: dict[str, Any]) -> list[Certification]:
    result: list[Certification] = []
    for item in _types(payload, ".Certification"):
        name = _text(item.get("name"))
        if name is None:
            continue
        period = _mapping(item.get("timePeriod"))
        result.append(
            Certification(
                name=name,
                issuer=_text(item.get("authority")),
                issued=_date(period.get("startDate")),
                expires=_date(period.get("endDate")),
                credential_id=_text(item.get("licenseNumber")),
            )
        )
    return result


class LinkedInSessionProvider:
    name = ProviderName.LINKEDIN_SESSION
    endpoint = "https://www.linkedin.com/voyager/api/identity/profiles"

    def __init__(
        self,
        client: httpx.AsyncClient,
        li_at: str | None,
        jsessionid: str | None,
        calls_per_day: int,
    ) -> None:
        self._client = client
        self._li_at = li_at
        self._jsessionid = jsessionid
        self._quota = SlidingWindowLimiter(calls_per_day, 86_400)

    @property
    def configured(self) -> bool:
        return bool(self._li_at and self._jsessionid)

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult:
        del context
        if not self.configured:
            raise ProviderUnavailable("The authenticated LinkedIn provider is not configured.")
        allowed, _, retry_after = await self._quota.allow("linkedin-session")
        if not allowed:
            raise RateLimitExceeded(
                f"The LinkedIn daily safety quota is exhausted; retry in {retry_after}s."
            )
        csrf = str(self._jsessionid).strip('"')
        endpoint = f"{self.endpoint}/{quote(profile_url.public_identifier, safe='')}/profileView"
        try:
            response = await self._client.get(
                endpoint,
                headers={
                    "Accept": "application/vnd.linkedin.normalized+json+2.1",
                    "csrf-token": csrf,
                    "x-li-lang": "en_US",
                    "x-restli-protocol-version": "2.0.0",
                    "Cookie": f'li_at={self._li_at}; JSESSIONID="{csrf}"',
                },
            )
        except httpx.HTTPError as error:
            raise ProviderRejected("LinkedIn could not be reached.") from error
        if response.status_code == 404:
            raise ProfileNotFound("LinkedIn did not return that profile.")
        if response.status_code in {401, 403}:
            raise ProviderUnavailable("The LinkedIn session is expired or was rejected.")
        if response.status_code in {429, 999}:
            raise RateLimitExceeded("LinkedIn rate-limited this deployment.")
        if response.status_code != 200:
            raise ProviderRejected(f"LinkedIn returned HTTP {response.status_code}.")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise ProviderRejected("LinkedIn returned invalid JSON.") from error
        entity = _profile_entity(payload)
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
            for item in _types(payload, ".Skill")
            if (name := _text(item.get("name"))) is not None
        ]
        languages = [
            Language(name=name, proficiency=_text(item.get("proficiency")))
            for item in _types(payload, ".Language")
            if (name := _text(item.get("name"))) is not None
        ]
        profile = ProfileData(
            name=profile_name,
            headline=_text(entity.get("headline")),
            location=_text(entity.get("locationName")),
            about=_text(entity.get("summary")),
            experience=_experiences(payload),
            education=_education(payload),
            skills=skills,
            certifications=_certifications(payload),
            languages=languages,
            images=ProfileImages(
                profile=_image(picture.get("displayImageReference", picture.get("displayImage"))),
                background=_image(
                    background.get("displayImageReference", background.get("displayImage"))
                ),
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
