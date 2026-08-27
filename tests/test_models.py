from datetime import date

import pytest
from pydantic import ValidationError

from profileproof.models import DateRange, ProfileData, ProviderName, ResolveRequest
from profileproof.service import profile_completeness


def test_date_range_rejects_reverse_order() -> None:
    with pytest.raises(ValidationError):
        DateRange(start=date(2025, 1, 1), end=date(2024, 1, 1))


def test_current_date_range_rejects_end() -> None:
    with pytest.raises(ValidationError):
        DateRange(end=date(2024, 1, 1), is_current=True)


def test_skills_are_trimmed_and_deduplicated() -> None:
    profile = ProfileData(skills=[" Python ", "Python", "", "C++"])
    assert profile.skills == ["Python", "C++"]


def test_consent_payload_requires_consent_provider() -> None:
    with pytest.raises(ValidationError):
        ResolveRequest(
            profile_url="https://www.linkedin.com/in/example-user",
            provider=ProviderName.DEMO,
            consented_profile=ProfileData(name="Example"),
        )


def test_consent_provider_requires_payload() -> None:
    with pytest.raises(ValidationError):
        ResolveRequest(
            profile_url="https://www.linkedin.com/in/example-user",
            provider=ProviderName.CONSENTED,
        )


def test_completeness_is_deterministic() -> None:
    score, fields = profile_completeness(ProfileData(name="Example", skills=["Python"]))
    assert score == 0.2
    assert fields == ["name", "skills"]
