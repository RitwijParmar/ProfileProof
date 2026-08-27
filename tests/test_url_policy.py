import pytest

from profileproof.errors import InvalidProfileUrl
from profileproof.url_policy import canonicalize_linkedin_profile_url


def test_canonicalizes_profile_url() -> None:
    result = canonicalize_linkedin_profile_url(
        " HTTPS://LINKEDIN.COM/in/Ada-Lovelace/?trk=public#about "
    )
    assert result.url == "https://www.linkedin.com/in/ada-lovelace"
    assert result.public_identifier == "ada-lovelace"


@pytest.mark.parametrize(
    "value",
    [
        "http://www.linkedin.com/in/example-user",
        "https://evil.example/in/example-user",
        "https://www.linkedin.com/company/example-user",
        "https://www.linkedin.com/in/a",
        "https://user:pass@www.linkedin.com/in/example-user",
        "https://www.linkedin.com:8443/in/example-user",
        "file:///etc/passwd",
        "https://127.0.0.1/in/example-user",
        "https://www.linkedin.com/in/example-user/extra",
        "not a url",
        "https://www.linkedin.com:bad/in/example-user",
    ],
)
def test_rejects_non_profile_urls(value: str) -> None:
    with pytest.raises(InvalidProfileUrl):
        canonicalize_linkedin_profile_url(value)
