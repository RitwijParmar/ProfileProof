from collections.abc import Callable

import httpx
import pytest

from profileproof.app import create_app
from profileproof.config import Settings


def _payload(public_identifier: str = "ritwij-aryan-parmar-716024211") -> dict[str, object]:
    return {
        "data": {},
        "included": [
            {
                "$type": "com.linkedin.voyager.identity.profile.Profile",
                "publicIdentifier": public_identifier,
                "firstName": "Ritwij Aryan",
                "lastName": "Parmar",
                "headline": "Software Engineer | Backend, LLM Inference",
                "locationName": "New York City Metropolitan Area",
                "summary": "Builds low-latency inference systems.",
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
                "$type": "com.linkedin.voyager.identity.profile.Position",
                "title": "Software Engineer",
                "companyName": "Quant Systems",
                "locationName": "New York",
                "description": "Built inference infrastructure.",
                "employmentType": "Full-time",
                "timePeriod": {"startDate": {"year": 2024, "month": 6}},
            },
            {
                "$type": "com.linkedin.voyager.identity.profile.Education",
                "schoolName": "University at Buffalo",
                "degreeName": "MS",
                "fieldOfStudy": "Computer Science",
                "timePeriod": {"startDate": {"year": 2023}, "endDate": {"year": 2025}},
            },
            {"$type": "com.linkedin.voyager.identity.profile.Skill", "name": "Python"},
            {
                "$type": "com.linkedin.voyager.identity.profile.Language",
                "name": "English",
                "proficiency": "FULL_PROFESSIONAL",
            },
            {
                "$type": "com.linkedin.voyager.identity.profile.Certification",
                "name": "Cloud Architect",
                "authority": "Google Cloud",
                "timePeriod": {"startDate": {"year": 2024, "month": 2}},
            },
        ],
    }


async def _request(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Response:
    app = create_app(
        Settings(environment="test", linkedin_li_at="li-at-secret", linkedin_jsessionid="ajax:123"),
        oidc_transport=httpx.MockTransport(handler),
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
        assert request.url.path.endswith("/ritwij-aryan-parmar-716024211/profileView")
        assert request.headers["csrf-token"] == "ajax:123"
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
async def test_default_provider_requires_linkedin_session(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/profiles/resolve",
        json={"profile_url": "https://www.linkedin.com/in/example-user"},
    )
    assert response.status_code == 424
    assert "authenticated LinkedIn" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(404, 404), (401, 424), (403, 424), (429, 429), (999, 429), (500, 502)],
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
