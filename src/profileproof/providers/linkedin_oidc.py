from typing import Any

import httpx
from pydantic import HttpUrl, ValidationError

from profileproof.errors import AuthenticationRequired, ProviderRejected
from profileproof.models import ProfileData, ProfileImages, ProviderName
from profileproof.url_policy import CanonicalProfileUrl

from .base import ProviderContext, ProviderResult


class LinkedInOidcProvider:
    name = ProviderName.LINKEDIN_OIDC
    endpoint = "https://api.linkedin.com/v2/userinfo"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult:
        del profile_url
        if not context.authorization or not context.authorization.startswith("Bearer "):
            raise AuthenticationRequired(
                "Pass an owner-authorized LinkedIn OIDC access token as a Bearer token."
            )
        try:
            response = await self._client.get(
                self.endpoint,
                headers={"Authorization": context.authorization, "Accept": "application/json"},
            )
        except httpx.HTTPError as error:
            raise ProviderRejected("LinkedIn OIDC could not be reached.") from error
        if response.status_code in {401, 403}:
            raise AuthenticationRequired("LinkedIn rejected or expired the OIDC access token.")
        if response.status_code != 200:
            raise ProviderRejected(f"LinkedIn OIDC returned HTTP {response.status_code}.")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as error:
            raise ProviderRejected("LinkedIn OIDC returned invalid JSON.") from error
        name = payload.get("name")
        picture = payload.get("picture")
        try:
            profile_image = HttpUrl(picture) if isinstance(picture, str) else None
        except ValidationError as error:
            raise ProviderRejected("LinkedIn OIDC returned an invalid picture URL.") from error
        profile = ProfileData(
            name=name if isinstance(name, str) else None,
            images=ProfileImages(profile=profile_image),
        )
        return ProviderResult(
            profile=profile,
            mode="official_oidc_self_profile",
            consented=True,
            limitations=[
                "OIDC returns the authenticated member's lite profile, not arbitrary profiles.",
                "Experience, education, skills, certifications, and languages are unavailable "
                "through self-service OIDC scopes.",
            ],
        )
