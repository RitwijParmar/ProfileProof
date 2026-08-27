from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from profileproof.errors import (
    ProfileNotFound,
    ProviderRejected,
    ProviderUnavailable,
    RateLimitExceeded,
)
from profileproof.models import ProfileResponse, ProviderName
from profileproof.providers.base import ProviderContext, ProviderResult
from profileproof.url_policy import CanonicalProfileUrl

_MAX_RESPONSE_BYTES = 1_048_576
_POINTER_HOST = "storage.googleapis.com"
_ALLOWED_RELAY_SUFFIXES = (".serveousercontent.com", ".serveo.net")


class ResidentialRelayProvider:
    """Forward direct acquisition to an automatically discovered residential worker."""

    name = ProviderName.LINKEDIN_DIRECT

    def __init__(self, client: httpx.AsyncClient, pointer_url: str) -> None:
        pointer = urlsplit(pointer_url)
        if (
            pointer.scheme != "https"
            or pointer.hostname != _POINTER_HOST
            or pointer.username
            or pointer.password
            or pointer.port not in (None, 443)
        ):
            raise ValueError("relay pointer must be an HTTPS storage.googleapis.com URL")
        self._client = client
        self._pointer_url = pointer_url

    @staticmethod
    def _validate_origin(value: str) -> str:
        origin = value.strip().rstrip("/")
        parsed = urlsplit(origin)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not hostname.endswith(_ALLOWED_RELAY_SUFFIXES)
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderUnavailable("The residential relay pointer is invalid.")
        return origin

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult:
        del context
        try:
            pointer_response = await self._client.get(self._pointer_url)
            pointer_response.raise_for_status()
            origin = self._validate_origin(pointer_response.text)
            response = await self._client.post(
                f"{origin}/v1/profiles/resolve",
                json={"profile_url": profile_url.url, "provider": "linkedin_direct"},
                headers={"Accept": "application/json"},
            )
        except ProviderUnavailable:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise ProviderUnavailable(
                "The residential acquisition relay is unreachable."
            ) from error

        if response.status_code == 404:
            raise ProfileNotFound("LinkedIn did not return this public profile.")
        if response.status_code == 429:
            raise RateLimitExceeded("The residential acquisition relay is rate limited.")
        if response.status_code != 200:
            raise ProviderRejected(
                f"The residential acquisition relay returned HTTP {response.status_code}."
            )
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ProviderRejected("The residential acquisition relay response was too large.")
        try:
            upstream = ProfileResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise ProviderRejected(
                "The residential acquisition relay returned an invalid response."
            ) from error
        if upstream.public_identifier.casefold() != profile_url.public_identifier.casefold():
            raise ProviderRejected("The residential acquisition relay returned another profile.")

        return ProviderResult(
            profile=upstream.profile,
            mode=upstream.source.mode,
            consented=upstream.source.consented,
            licensed=upstream.source.licensed,
            match_confidence=upstream.source.match_confidence,
            dataset_version=upstream.source.dataset_version,
            limitations=upstream.source.limitations,
            warnings=[*upstream.meta.warnings, "residential_relay"],
        )
