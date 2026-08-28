from dataclasses import dataclass, field
from typing import Protocol

from profileproof.models import ProfileData, ProviderName
from profileproof.url_policy import CanonicalProfileUrl


@dataclass(frozen=True)
class ProviderContext:
    authorization: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    profile: ProfileData
    mode: str
    consented: bool
    licensed: bool = False
    match_confidence: float | None = None
    dataset_version: str | None = None
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ProfileProvider(Protocol):
    name: ProviderName

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult: ...
