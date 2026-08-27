import json
from collections.abc import Callable

import httpx
import pytest

from profileproof.app import create_app
from profileproof.config import Settings
from profileproof.providers.linkedin_session import _public_date, _public_person, _public_text


def _public_html(
    public_identifier: str = "ritwij-aryan-parmar-716024211",
    name: str = "Ritwij Aryan Parmar",
) -> str:
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Person",
                "url": f"https://www.linkedin.com/in/{public_identifier}",
                "name": name,
                "jobTitle": ["Principal Software Engineer"],
                "disambiguatingDescription": "Builds low-latency systems.",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "New York",
                    "addressCountry": "US",
                },
                "worksFor": [
                    {
                        "@type": "Organization",
                        "name": "Quant Systems",
                        "member": {
                            "@type": "OrganizationRole",
                            "roleName": "Principal Software Engineer",
                            "description": "Built market infrastructure.",
                            "startDate": "2024-06",
                        },
                    }
                ],
                "alumniOf": [
                    {
                        "@type": "EducationalOrganization",
                        "name": "University at Buffalo",
                        "member": {
                            "@type": "OrganizationRole",
                            "roleName": "MS Computer Science",
                            "startDate": 2023,
                            "endDate": 2025,
                        },
                    }
                ],
                "knowsAbout": ["Python", "Distributed Systems"],
                "knowsLanguage": [{"name": "English"}],
                "image": {
                    "@type": "ImageObject",
                    "contentUrl": "https://media.licdn.com/profile.jpg",
                },
            }
        ],
    }
    return f'<html><script type="application/ld+json">{json.dumps(payload)}</script></html>'


def test_public_helpers_fail_closed() -> None:
    assert _public_date({}) is None
    assert _public_date(10_000) is None
    assert _public_date("2024-99") is None
    assert _public_text("*** **") is None
    assert _public_person('<script type="application/ld+json">not-json</script>') == {}


def _payload(public_identifier: str = "ritwij-aryan-parmar-716024211") -> dict[str, object]:
    profile_id = "ACoAATARGET"
    profile_urn = f"urn:li:fsd_profile:{profile_id}"
    return {
        "data": {"*elements": [profile_urn]},
        "included": [
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                "entityUrn": profile_urn,
                "publicIdentifier": public_identifier,
                "firstName": "Ritwij Aryan",
                "lastName": "Parmar",
                "headline": {
                    "text": "Software Engineer | Backend, LLM Inference",
                    "attributes": [],
                },
                "locationName": "New York City Metropolitan Area",
                "summary": {"text": "Builds low-latency inference systems.", "attributes": []},
                "*profilePositionGroups": "urn:li:collection:position-groups",
                "*profileEducations": "urn:li:collection:educations",
                "*profileSkills": "urn:li:collection:skills",
                "*profileCertifications": "urn:li:collection:certifications",
                "*profileLanguages": "urn:li:collection:languages",
                "profilePicture": {
                    "displayImageReference": {
                        "rootUrl": "https://media.licdn.com/",
                        "artifacts": [
                            {
                                "width": 100,
                                "height": 100,
                                "fileIdentifyingUrlPathSegment": "photo.jpg",
                            }
                        ],
                    }
                },
            },
            {
                "$type": "com.linkedin.restli.common.CollectionResponse",
                "entityUrn": "urn:li:collection:position-groups",
                "*elements": [f"urn:li:fsd_positionGroup:({profile_id},group-1)"],
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.PositionGroup",
                "entityUrn": f"urn:li:fsd_positionGroup:({profile_id},group-1)",
                "*profilePositionInPositionGroup": "urn:li:collection:positions",
            },
            {
                "$type": "com.linkedin.restli.common.CollectionResponse",
                "entityUrn": "urn:li:collection:positions",
                "*elements": [f"urn:li:fsd_position:({profile_id},position-1)"],
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Position",
                "entityUrn": f"urn:li:fsd_position:({profile_id},position-1)",
                "title": {"text": "Software Engineer", "attributes": []},
                "companyName": "Quant Systems",
                "locationName": "New York",
                "description": "Built inference infrastructure.",
                "employmentType": "Full-time",
                "dateRange": {"start": {"year": 2024, "month": 6}},
            },
            {
                "$type": "com.linkedin.restli.common.CollectionResponse",
                "entityUrn": "urn:li:collection:educations",
                "*elements": [f"urn:li:fsd_education:({profile_id},education-1)"],
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Education",
                "entityUrn": f"urn:li:fsd_education:({profile_id},education-1)",
                "schoolName": "University at Buffalo",
                "degreeName": "MS",
                "fieldOfStudy": "Computer Science",
                "dateRange": {"start": {"year": 2023}, "end": {"year": 2025}},
            },
            {
                "$type": "com.linkedin.restli.common.CollectionResponse",
                "entityUrn": "urn:li:collection:skills",
                "*elements": [f"urn:li:fsd_skill:({profile_id},skill-1)"],
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Skill",
                "entityUrn": f"urn:li:fsd_skill:({profile_id},skill-1)",
                "name": "Python",
            },
            {
                "$type": "com.linkedin.restli.common.CollectionResponse",
                "entityUrn": "urn:li:collection:languages",
                "*elements": [f"urn:li:fsd_language:({profile_id},language-1)"],
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Language",
                "entityUrn": f"urn:li:fsd_language:({profile_id},language-1)",
                "name": "English",
                "proficiency": "FULL_PROFESSIONAL",
            },
            {
                "$type": "com.linkedin.restli.common.CollectionResponse",
                "entityUrn": "urn:li:collection:certifications",
                "*elements": [f"urn:li:fsd_certification:({profile_id},certification-1)"],
            },
            {
                "$type": "com.linkedin.voyager.dash.identity.profile.Certification",
                "entityUrn": f"urn:li:fsd_certification:({profile_id},certification-1)",
                "name": "Cloud Architect",
                "authority": "Google Cloud",
                "dateRange": {"start": {"year": 2024, "month": 2}},
            },
        ],
    }


async def _request(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Response:
    app = create_app(
        Settings(environment="test", linkedin_li_at="li-at-secret", linkedin_jsessionid="ajax:123"),
        upstream_transport=httpx.MockTransport(handler),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        return await client.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/ritwij-aryan-parmar-716024211"},
        )


async def _public_request(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Response:
    app = create_app(
        Settings(environment="test", linkedin_min_interval_seconds=0),
        upstream_transport=httpx.MockTransport(handler),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        return await client.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/ritwij-aryan-parmar-716024211"},
        )


@pytest.mark.asyncio
async def test_linkedin_session_maps_real_profile_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/identity/dash/profiles")
        assert request.url.params["q"] == "memberIdentity"
        assert request.url.params["memberIdentity"] == "ritwij-aryan-parmar-716024211"
        assert request.url.params["decorationId"].endswith("FullProfileWithEntities-101")
        assert request.headers["csrf-token"] == "ajax:123"
        assert request.headers["user-agent"].startswith("Mozilla/5.0")
        assert request.headers["accept-language"] == "en-US,en;q=0.9"
        assert request.headers["referer"].endswith("/in/ritwij-aryan-parmar-716024211/")
        assert "li_at=li-at-secret" in request.headers["cookie"]
        return httpx.Response(200, json=_payload())

    response = await _request(handler)
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["name"] == "Ritwij Aryan Parmar"
    assert body["profile"]["experience"][0]["company"] == "Quant Systems"
    assert body["profile"]["education"][0]["school"] == "University at Buffalo"
    assert body["profile"]["skills"] == ["Python"]
    assert body["profile"]["images"]["profile"] == "https://media.licdn.com/photo.jpg"
    assert body["source"]["mode"] == "authenticated_linkedin_voyager"
    assert body["meta"]["warnings"] == ["authenticated_session", "undocumented_upstream"]


@pytest.mark.asyncio
async def test_linkedin_session_resolves_target_graph_without_cross_profile_rows() -> None:
    payload = _payload()
    included = payload["included"]
    assert isinstance(included, list)
    included.insert(
        0,
        {
            "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
            "entityUrn": "urn:li:fsd_profile:DECOY",
            "publicIdentifier": "different-profile",
            "firstName": "Wrong",
            "lastName": "Person",
        },
    )
    included.append(
        {
            "$type": "com.linkedin.voyager.dash.identity.profile.Position",
            "entityUrn": "urn:li:fsd_position:(DECOY,position-1)",
            "title": "Contaminating role",
            "companyName": "Wrong Company",
        }
    )
    response = await _request(lambda _request: httpx.Response(200, json=payload))
    body = response.json()
    assert response.status_code == 200
    assert body["profile"]["name"] == "Ritwij Aryan Parmar"
    assert [item["company"] for item in body["profile"]["experience"]] == ["Quant Systems"]


@pytest.mark.asyncio
async def test_linkedin_session_serializes_and_paces_uncached_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(request.url.params["memberIdentity"]))

    app = create_app(
        Settings(
            environment="test",
            linkedin_li_at="li-at-secret",
            linkedin_jsessionid="ajax:123",
            linkedin_min_interval_seconds=0.05,
        ),
        upstream_transport=httpx.MockTransport(handler),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        first = await client.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/first-profile"},
        )
        second = await client.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/second-profile"},
        )
    assert first.status_code == 200
    assert second.status_code == 200


@pytest.mark.asyncio
async def test_default_provider_uses_public_direct_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/in/ritwij-aryan-parmar-716024211"
        assert "cookie" not in request.headers
        return httpx.Response(200, text=_public_html())

    app = create_app(
        Settings(environment="test"),
        upstream_transport=httpx.MockTransport(handler),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/ritwij-aryan-parmar-716024211"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["provider"] == "linkedin_direct"
    assert body["source"]["mode"] == "public_linkedin_jsonld"
    assert body["profile"]["name"] == "Ritwij Aryan Parmar"
    assert body["profile"]["experience"][0]["company"] == "Quant Systems"
    assert body["profile"]["education"][0]["school"] == "University at Buffalo"
    assert body["profile"]["skills"] == ["Python", "Distributed Systems"]
    assert body["profile"]["languages"] == [{"name": "English"}]


@pytest.mark.asyncio
async def test_rejected_session_falls_back_to_public_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/voyager/api/"):
            return httpx.Response(302, headers={"location": "/uas/login"})
        return httpx.Response(200, text=_public_html())

    response = await _request(handler)
    assert response.status_code == 200
    assert response.json()["source"]["mode"] == "public_linkedin_jsonld"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(404, 404), (302, 424), (401, 424), (403, 424), (429, 429), (999, 429), (500, 502)],
)
async def test_public_direct_maps_failures(upstream_status: int, expected_status: int) -> None:
    response = await _public_request(lambda _request: httpx.Response(upstream_status))
    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_public_direct_rejects_unusable_documents() -> None:
    missing = await _public_request(lambda _request: httpx.Response(200, text="<html></html>"))
    oversized = await _public_request(lambda _request: httpx.Response(200, text="x" * 2_000_001))
    mismatch = await _public_request(
        lambda _request: httpx.Response(
            200,
            text=_public_html(public_identifier="different-profile"),
        )
    )
    redacted = await _public_request(
        lambda _request: httpx.Response(
            200,
            text=_public_html(name="********"),
        )
    )
    assert missing.status_code == 404
    assert oversized.status_code == 502
    assert mismatch.status_code == 502
    assert redacted.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(404, 404), (302, 424), (401, 424), (403, 424), (429, 429), (999, 429), (500, 502)],
)
async def test_linkedin_session_maps_failures(upstream_status: int, expected_status: int) -> None:
    response = await _request(lambda _request: httpx.Response(upstream_status))
    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_linkedin_session_rejects_invalid_json_and_identity_mismatch() -> None:
    invalid = await _request(lambda _request: httpx.Response(200, text="not-json"))
    mismatch = await _request(
        lambda _request: httpx.Response(200, json=_payload("different-profile"))
    )
    assert invalid.status_code == 502
    assert mismatch.status_code == 502
