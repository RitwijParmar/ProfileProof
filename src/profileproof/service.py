import hashlib
from datetime import UTC, datetime

from pydantic import HttpUrl

from profileproof.cache import TtlCache
from profileproof.models import (
    ProfileData,
    ProfileResponse,
    ProviderName,
    ResolveMeta,
    ResolveRequest,
    SourceInfo,
)
from profileproof.providers.base import ProfileProvider, ProviderContext, ProviderResult
from profileproof.url_policy import canonicalize_linkedin_profile_url


def profile_completeness(profile: ProfileData) -> tuple[float, list[str]]:
    values = {
        "name": profile.name,
        "headline": profile.headline,
        "location": profile.location,
        "about": profile.about,
        "experience": profile.experience,
        "education": profile.education,
        "skills": profile.skills,
        "certifications": profile.certifications,
        "languages": profile.languages,
        "images": profile.images.profile or profile.images.background,
    }
    present = [name for name, value in values.items() if value]
    return len(present) / len(values), present


class ProfileService:
    def __init__(
        self,
        providers: dict[ProviderName, ProfileProvider],
        cache: TtlCache[ProviderResult],
    ) -> None:
        self._providers = providers
        self._cache = cache

    async def resolve(
        self, request: ResolveRequest, request_id: str, authorization: str | None
    ) -> ProfileResponse:
        canonical = canonicalize_linkedin_profile_url(request.profile_url)
        provider = self._providers[request.provider]
        cacheable = request.provider == ProviderName.DEMO
        cache_key = hashlib.sha256(f"{request.provider}:{canonical.url}".encode()).hexdigest()
        result = await self._cache.get(cache_key) if cacheable else None
        cached = result is not None
        if result is None:
            result = await provider.fetch(
                canonical,
                ProviderContext(
                    authorization=authorization,
                    consented_profile=request.consented_profile,
                ),
            )
            if cacheable:
                await self._cache.put(cache_key, result)
        completeness, fields = profile_completeness(result.profile)
        return ProfileResponse(
            canonical_url=HttpUrl(canonical.url),
            public_identifier=canonical.public_identifier,
            profile=result.profile,
            source=SourceInfo(
                provider=request.provider,
                mode=result.mode,
                consented=result.consented,
                limitations=result.limitations,
            ),
            meta=ResolveMeta(
                request_id=request_id,
                fetched_at=datetime.now(UTC),
                cached=cached,
                completeness=completeness,
                fields_present=fields,
                warnings=result.warnings,
            ),
        )
