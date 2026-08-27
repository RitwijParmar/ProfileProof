from profileproof.errors import ProviderUnavailable
from profileproof.models import ProviderName
from profileproof.url_policy import CanonicalProfileUrl

from .base import ProviderContext, ProviderResult


class ConsentedProvider:
    name = ProviderName.CONSENTED

    async def fetch(
        self, profile_url: CanonicalProfileUrl, context: ProviderContext
    ) -> ProviderResult:
        del profile_url
        if context.consented_profile is None:
            raise ProviderUnavailable("The consented provider requires consented_profile data.")
        return ProviderResult(
            profile=context.consented_profile,
            mode="owner_supplied",
            consented=True,
            limitations=[
                "Data was supplied by the API caller and was not independently verified.",
                "ProfileProof normalizes the payload but does not persist it.",
            ],
        )
