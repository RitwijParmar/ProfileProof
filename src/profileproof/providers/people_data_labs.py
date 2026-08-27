from __future__ import annotations

from datetime import date
from typing import Any

import httpx

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
    ProviderName,
)
from profileproof.rate_limit import SlidingWindowLimiter
from profileproof.url_policy import CanonicalProfileUrl, canonicalize_linkedin_profile_url

from .base import ProviderContext, ProviderResult

_PROFESSIONAL_FIELDS = ",".join(
    (
        "full_name",
        "headline",
        "location_name",
        "summary",
        "experience.company.name",
        "experience.title.name",
        "experience.location_names",
        "experience.summary",
        "experience.start_date",
        "experience.end_date",
        "experience.is_primary",
        "education.school.name",
        "education.degrees",
        "education.majors",
        "education.summary",
        "education.start_date",
        "education.end_date",
        "skills",
        "certifications.name",
        "certifications.organization",
        "certifications.start_date",
        "certifications.end_date",
        "languages.name",
        "languages.proficiency",
        "linkedin_url",
        "linkedin_username",
        "dataset_version",
    )
)
_LANGUAGE_PROFICIENCY = {
    1: "Elementary proficiency",
    2: "Limited working proficiency",
    3: "Professional working proficiency",
    4: "Full professional proficiency",
    5: "Native or bilingual proficiency",
}


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _date(value: object) -> date | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parts = [int(part) for part in raw[:10].split("-")]
        if len(parts) == 1:
            return date(parts[0], 1, 1)
        if len(parts) == 2:
            return date(parts[0], parts[1], 1)
        return date(parts[0], parts[1], parts[2])
    except (ValueError, IndexError):
        return None


def _experience(data: dict[str, Any]) -> list[Experience]:
    results: list[Experience] = []
    for item in _items(data.get("experience")):
        title = _text(_mapping(item.get("title")).get("name"))
        company = _text(_mapping(item.get("company")).get("name"))
        if title is None or company is None:
            continue
        locations = item.get("location_names")
        location = (
            next((_text(value) for value in locations if _text(value)), None)
            if isinstance(locations, list)
            else None
        )
        end = _date(item.get("end_date"))
        results.append(
            Experience(
                title=title,
                company=company,
                location=location,
                description=_text(item.get("summary")),
                dates=DateRange(
                    start=_date(item.get("start_date")),
                    end=end,
                    is_current=bool(item.get("is_primary")) and end is None,
                ),
            )
        )
    return results


def _education(data: dict[str, Any]) -> list[Education]:
    results: list[Education] = []
    for item in _items(data.get("education")):
        school = _text(_mapping(item.get("school")).get("name"))
        if school is None:
            continue
        degrees = item.get("degrees")
        majors = item.get("majors")
        end = _date(item.get("end_date"))
        results.append(
            Education(
                school=school,
                degree=", ".join(str(value) for value in degrees)
                if isinstance(degrees, list)
                else None,
                field_of_study=", ".join(str(value) for value in majors)
                if isinstance(majors, list)
                else None,
                description=_text(item.get("summary")),
                dates=DateRange(
                    start=_date(item.get("start_date")),
                    end=end,
                    is_current=end is None,
                ),
            )
        )
    return results


def _certifications(data: dict[str, Any]) -> list[Certification]:
    return [
        Certification(
            name=name,
            issuer=_text(item.get("organization")),
            issued=_date(item.get("start_date")),
            expires=_date(item.get("end_date")),
        )
        for item in _items(data.get("certifications"))
        if (name := _text(item.get("name"))) is not None
    ]


def _languages(data: dict[str, Any]) -> list[Language]:
    results: list[Language] = []
    for item in _items(data.get("languages")):
        name = _text(item.get("name"))
        if name is None:
            continue
        raw_proficiency = item.get("proficiency")
        proficiency = (
            _LANGUAGE_PROFICIENCY.get(raw_proficiency) if isinstance(raw_proficiency, int) else None
        )
        results.append(Language(name=name, proficiency=proficiency))
    return results


class PeopleDataLabsProvider:
    name = ProviderName.PEOPLE_DATA_LABS
    endpoint = "https://api.peopledatalabs.com/v5/person/enrich"

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None,
        min_likelihood: int,
        calls_per_day: int,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._min_likelihood = min_likelihood
        self._quota = SlidingWindowLimiter(calls_per_day, 86_400)

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult:
        del context
        if not self._api_key:
            raise ProviderUnavailable(
                "The licensed People Data Labs provider is not configured on this deployment."
            )
        allowed, _, retry_after = await self._quota.allow("licensed-provider")
        if not allowed:
            raise RateLimitExceeded(
                f"The licensed-provider daily safety quota is exhausted; retry in {retry_after}s."
            )
        try:
            response = await self._client.get(
                self.endpoint,
                headers={
                    "X-Api-Key": self._api_key,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                },
                params={
                    "profile": profile_url.url,
                    "min_likelihood": self._min_likelihood,
                    "include_if_matched": "true",
                    "titlecase": "true",
                    "data_include": _PROFESSIONAL_FIELDS,
                },
            )
        except httpx.HTTPError as error:
            raise ProviderRejected("People Data Labs could not be reached.") from error
        if response.status_code == 404:
            raise ProfileNotFound("No sufficiently confident licensed profile match was found.")
        if response.status_code in {401, 403}:
            raise ProviderUnavailable("People Data Labs rejected the configured API key.")
        if response.status_code == 429:
            raise RateLimitExceeded("People Data Labs rate-limited this deployment.")
        if response.status_code != 200:
            raise ProviderRejected(f"People Data Labs returned HTTP {response.status_code}.")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise ProviderRejected("People Data Labs returned invalid JSON.") from error
        data = _mapping(payload.get("data"))
        likelihood = payload.get("likelihood")
        if not isinstance(likelihood, int) or likelihood < self._min_likelihood:
            raise ProviderRejected("People Data Labs returned an insufficient match confidence.")
        returned_url = _text(data.get("linkedin_url"))
        if returned_url:
            try:
                normalized_url = (
                    returned_url if "://" in returned_url else f"https://{returned_url}"
                )
                if normalized_url.startswith("http://"):
                    normalized_url = f"https://{normalized_url.removeprefix('http://')}"
                returned = canonicalize_linkedin_profile_url(normalized_url)
            except InvalidProfileUrl as error:
                raise ProviderRejected(
                    "People Data Labs returned an invalid LinkedIn identity."
                ) from error
            if returned.public_identifier.casefold() != profile_url.public_identifier.casefold():
                raise ProviderRejected("People Data Labs returned a different LinkedIn identity.")
        skills = data.get("skills")
        profile = ProfileData(
            name=_text(data.get("full_name")),
            headline=_text(data.get("headline")),
            location=_text(data.get("location_name")),
            about=_text(data.get("summary")),
            experience=_experience(data),
            education=_education(data),
            skills=[str(value) for value in skills] if isinstance(skills, list) else [],
            certifications=_certifications(data),
            languages=_languages(data),
        )
        return ProviderResult(
            profile=profile,
            mode="licensed_dataset_enrichment",
            consented=False,
            licensed=True,
            match_confidence=likelihood / 10,
            dataset_version=_text(data.get("dataset_version")),
            limitations=[
                "This is a licensed dataset match, not a live scrape of LinkedIn.",
                "Field availability and freshness depend on the upstream dataset subscription.",
            ],
            warnings=["third_party_dataset"],
        )
