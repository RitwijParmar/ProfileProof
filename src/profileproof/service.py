import asyncio
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
from profileproof.url_policy import CanonicalProfileUrl, canonicalize_linkedin_profile_url


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
        self._inflight: dict[str, asyncio.Lock] = {}
        self._inflight_users: dict[str, int] = {}
        self._inflight_guard = asyncio.Lock()

    async def _fetch_cacheable(
        self,
        cache_key: str,
        provider: ProfileProvider,
        canonical: CanonicalProfileUrl,
        context: ProviderContext,
    ) -> tuple[ProviderResult, bool]:
        cached_result = await self._cache.get(cache_key)
        if cached_result is not None:
            return cached_result, True
        async with self._inflight_guard:
            lock = self._inflight.setdefault(cache_key, asyncio.Lock())
            self._inflight_users[cache_key] = self._inflight_users.get(cache_key, 0) + 1
        try:
            async with lock:
                cached_result = await self._cache.get(cache_key)
                if cached_result is not None:
                    return cached_result, True
                result = await provider.fetch(canonical, context)
                await self._cache.put(cache_key, result)
                return result, False
        finally:
            async with self._inflight_guard:
                users = self._inflight_users[cache_key] - 1
                if users == 0:
                    self._inflight.pop(cache_key, None)
                    self._inflight_users.pop(cache_key, None)
                else:
                    self._inflight_users[cache_key] = users

    async def resolve(
        self, request: ResolveRequest, request_id: str, authorization: str | None
    ) -> ProfileResponse:
        canonical = canonicalize_linkedin_profile_url(request.profile_url)
        provider = self._providers[request.provider]
        cache_key = hashlib.sha256(f"{request.provider}:{canonical.url}".encode()).hexdigest()
        context = ProviderContext(
            authorization=authorization,
        )
        result, cached = await self._fetch_cacheable(cache_key, provider, canonical, context)
        completeness, fields = profile_completeness(result.profile)
        return ProfileResponse(
            canonical_url=HttpUrl(canonical.url),
            public_identifier=canonical.public_identifier,
            profile=result.profile,
            source=SourceInfo(
                provider=request.provider,
                mode=result.mode,
                consented=result.consented,
                licensed=result.licensed,
                match_confidence=result.match_confidence,
                dataset_version=result.dataset_version,
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
