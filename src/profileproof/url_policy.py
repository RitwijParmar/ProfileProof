import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit

from .errors import InvalidProfileUrl

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,98}[A-Za-z0-9]$")
_ALLOWED_HOSTS = {"linkedin.com", "www.linkedin.com"}


@dataclass(frozen=True)
class CanonicalProfileUrl:
    url: str
    public_identifier: str


def canonicalize_linkedin_profile_url(value: str) -> CanonicalProfileUrl:
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError as error:
        raise InvalidProfileUrl("The profile URL could not be parsed.") from error
    if parsed.scheme.lower() != "https":
        raise InvalidProfileUrl("Only HTTPS LinkedIn profile URLs are accepted.")
    if parsed.username or parsed.password:
        raise InvalidProfileUrl("Credentials must not be embedded in a profile URL.")
    if parsed.hostname is None or parsed.hostname.lower() not in _ALLOWED_HOSTS:
        raise InvalidProfileUrl("The host must be linkedin.com or www.linkedin.com.")
    try:
        port = parsed.port
    except ValueError as error:
        raise InvalidProfileUrl("The profile URL contains an invalid port.") from error
    if port not in (None, 443):
        raise InvalidProfileUrl("Only the standard HTTPS port is accepted.")
    path = unquote(parsed.path)
    parts = [part for part in path.split("/") if part]
    if len(parts) != 2 or parts[0].lower() != "in" or not _SLUG.fullmatch(parts[1]):
        raise InvalidProfileUrl("Expected a public profile URL shaped like /in/public-identifier.")
    slug = parts[1].lower()
    canonical = urlunsplit(("https", "www.linkedin.com", f"/in/{slug}", "", ""))
    return CanonicalProfileUrl(canonical, slug)
