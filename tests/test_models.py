from datetime import date

import pytest
from pydantic import ValidationError

from profileproof.models import DateRange, ProfileData
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


def test_completeness_is_deterministic() -> None:
    score, fields = profile_completeness(ProfileData(name="Example", skills=["Python"]))
    assert score == 0.2
    assert fields == ["name", "skills"]
