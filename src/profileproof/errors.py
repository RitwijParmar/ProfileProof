class ProfileProofError(Exception):
    status_code = 500
    title = "Internal server error"
    problem_type = "https://profileproof.dev/problems/internal"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidProfileUrl(ProfileProofError):
    status_code = 422
    title = "Invalid LinkedIn profile URL"
    problem_type = "https://profileproof.dev/problems/invalid-profile-url"


class ProviderUnavailable(ProfileProofError):
    status_code = 424
    title = "Profile provider unavailable"
    problem_type = "https://profileproof.dev/problems/provider-unavailable"


class ProfileNotFound(ProfileProofError):
    status_code = 404
    title = "Profile not found"
    problem_type = "https://profileproof.dev/problems/profile-not-found"


class ProviderRejected(ProfileProofError):
    status_code = 502
    title = "Upstream provider rejected the request"
    problem_type = "https://profileproof.dev/problems/provider-rejected"


class AuthenticationRequired(ProfileProofError):
    status_code = 401
    title = "Authentication required"
    problem_type = "https://profileproof.dev/problems/authentication-required"


class RateLimitExceeded(ProfileProofError):
    status_code = 429
    title = "Rate limit exceeded"
    problem_type = "https://profileproof.dev/problems/rate-limit"

    def __init__(self, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.retry_after = retry_after
