from datetime import UTC, datetime

import httpx
import pytest

from profileproof.errors import ProviderRejected, ProviderUnavailable, RateLimitExceeded
from profileproof.providers.base import ProviderContext
from profileproof.providers.relay import ResidentialRelayProvider
from profileproof.url_policy import canonicalize_linkedin_profile_url

POINTER = "https://storage.googleapis.com/profileproof-pointer/current-origin.txt"
ORIGIN = "https://abc123.serveousercontent.com"
CANONICAL = canonicalize_linkedin_profile_url("https://linkedin.com/in/seanthorne")


def _profile(public_identifier: str = "seanthorne") -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "canonical_url": f"https://www.linkedin.com/in/{public_identifier}",
        "public_identifier": public_identifier,
        "profile": {
            "name": "Sean Thorne",
            "experience": [],
            "education": [],
            "skills": [],
            "certifications": [],
            "languages": [],
            "images": {},
        },
        "source": {
            "provider": "linkedin_direct",
            "mode": "public_linkedin_jsonld",
            "consented": False,
            "licensed": False,
            "limitations": ["Public page fields only."],
        },
        "meta": {
            "request_id": "upstream-request",
            "fetched_at": datetime.now(UTC).isoformat(),
            "cached": False,
            "completeness": 0.1,
            "fields_present": ["name"],
            "warnings": ["public_fallback"],
        },
    }


@pytest.mark.asyncio
async def test_relay_returns_validated_profile() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == POINTER:
            return httpx.Response(200, text=ORIGIN)
        assert str(request.url) == f"{ORIGIN}/v1/profiles/resolve"
        assert request.method == "POST"
        return httpx.Response(200, json=_profile())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ResidentialRelayProvider(client, POINTER).fetch(CANONICAL, ProviderContext())
    assert result.profile.name == "Sean Thorne"
    assert result.mode == "public_linkedin_jsonld"
    assert result.warnings == ["public_fallback", "residential_relay"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_relay_maps_upstream_failures(status: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == POINTER:
            return httpx.Response(200, text=ORIGIN)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ResidentialRelayProvider(client, POINTER)
        expected = RateLimitExceeded if status == 429 else ProviderRejected
        with pytest.raises(expected):
            await provider.fetch(CANONICAL, ProviderContext())


@pytest.mark.asyncio
async def test_relay_rejects_unsafe_origin_and_profile_mismatch() -> None:
    unsafe = httpx.MockTransport(lambda request: httpx.Response(200, text="https://127.0.0.1"))
    async with httpx.AsyncClient(transport=unsafe) as client:
        with pytest.raises(ProviderUnavailable):
            await ResidentialRelayProvider(client, POINTER).fetch(CANONICAL, ProviderContext())

    async def mismatch_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == POINTER:
            return httpx.Response(200, text=ORIGIN)
        return httpx.Response(200, json=_profile("someone-else"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(mismatch_handler)) as client:
        with pytest.raises(ProviderRejected):
            await ResidentialRelayProvider(client, POINTER).fetch(CANONICAL, ProviderContext())


def test_relay_rejects_unsafe_pointer_configuration() -> None:
    with pytest.raises(ValueError):
        ResidentialRelayProvider(httpx.AsyncClient(), "https://example.com/pointer")
