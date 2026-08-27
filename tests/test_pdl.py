import asyncio
from collections.abc import Callable

import httpx
import pytest

from profileproof.app import create_app
from profileproof.config import Settings


def _payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "full_name": "Sean Thorne",
        "headline": "Founder",
        "location_name": "San Francisco, California, United States",
        "summary": "Builds data products.",
        "linkedin_url": "linkedin.com/in/seanthorne",
        "linkedin_username": "seanthorne",
        "dataset_version": "34.2",
        "skills": ["Data", "Python"],
        "experience": [
            {
                "company": {"name": "People Data Labs"},
                "title": {"name": "Co-founder and CEO"},
                "location_names": ["San Francisco"],
                "summary": "Built the company.",
                "start_date": "2015-03",
                "end_date": None,
                "is_primary": True,
            },
            {"company": {}, "title": {"name": "Ignored"}},
        ],
        "education": [
            {
                "school": {"name": "University of Oregon"},
                "degrees": ["Bachelor of Science"],
                "majors": ["Economics"],
                "summary": "Economics",
                "start_date": "2010",
                "end_date": "2012-06-01",
            },
            {"school": {}},
        ],
        "certifications": [
            {
                "name": "Machine Learning",
                "organization": "Coursera",
                "start_date": "2022-03",
                "end_date": "invalid-date",
            },
            {"organization": "Ignored"},
        ],
        "languages": [
            {"name": "English", "proficiency": 5},
            {"name": "French", "proficiency": 9},
            {"proficiency": 3},
        ],
        "profile_pic_url": "not-a-url",
    }
    data.update(overrides)
    return {"status": 200, "likelihood": 10, "matched": ["profile"], "data": data}


async def _request(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    calls_per_day: int = 50,
) -> httpx.Response:
    app = create_app(
        Settings(
            environment="test",
            pdl_api_key="test-key",
            pdl_calls_per_instance_per_day=calls_per_day,
        ),
        oidc_transport=httpx.MockTransport(handler),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        return await client.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/seanthorne",
                "provider": "people_data_labs",
            },
        )


@pytest.mark.asyncio
async def test_pdl_maps_real_professional_profile_and_provenance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.peopledatalabs.com"
        assert request.headers["x-api-key"] == "test-key"
        assert request.url.params["profile"] == "https://www.linkedin.com/in/seanthorne"
        assert request.url.params["min_likelihood"] == "8"
        assert "emails" not in request.url.params["data_include"]
        assert "phone" not in request.url.params["data_include"]
        return httpx.Response(200, json=_payload())

    response = await _request(handler)
    assert response.status_code == 200
    result = response.json()
    assert result["profile"]["name"] == "Sean Thorne"
    assert result["profile"]["experience"][0]["title"] == "Co-founder and CEO"
    assert result["profile"]["experience"][0]["dates"] == {
        "start": "2015-03-01",
        "is_current": True,
    }
    assert result["profile"]["education"][0]["degree"] == "Bachelor of Science"
    assert result["profile"]["education"][0]["dates"]["start"] == "2010-01-01"
    assert result["profile"]["certifications"][0]["issued"] == "2022-03-01"
    assert "expires" not in result["profile"]["certifications"][0]
    assert result["profile"]["languages"][0]["proficiency"] == ("Native or bilingual proficiency")
    assert result["source"]["licensed"] is True
    assert result["source"]["match_confidence"] == 1.0
    assert result["source"]["dataset_version"] == "34.2"
    assert result["meta"]["warnings"] == ["third_party_dataset"]


@pytest.mark.asyncio
async def test_pdl_is_unavailable_without_key(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/profiles/resolve",
        json={
            "profile_url": "https://www.linkedin.com/in/seanthorne",
            "provider": "people_data_labs",
        },
    )
    assert response.status_code == 424
    assert "not configured" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "expected_status"),
    [(404, 404), (401, 424), (403, 424), (429, 429), (500, 502)],
)
async def test_pdl_maps_upstream_failures(upstream_status: int, expected_status: int) -> None:
    response = await _request(lambda _request: httpx.Response(upstream_status))
    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_pdl_rejects_invalid_json() -> None:
    response = await _request(lambda _request: httpx.Response(200, text="not-json"))
    assert response.status_code == 502
    assert "invalid JSON" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"status": 200, "likelihood": 3, "data": {}},
        _payload(linkedin_url="linkedin.com/in/different-person"),
        _payload(linkedin_url="example.com/not-linkedin"),
    ],
)
async def test_pdl_rejects_untrustworthy_matches(payload: dict[str, object]) -> None:
    response = await _request(lambda _request: httpx.Response(200, json=payload))
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_pdl_handles_network_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    response = await _request(handler)
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_pdl_enforces_per_instance_safety_quota() -> None:
    app = create_app(
        Settings(
            environment="test",
            pdl_api_key="test-key",
            pdl_calls_per_instance_per_day=1,
            cache_ttl_seconds=0,
        ),
        oidc_transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=_payload())),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        first = await client.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/seanthorne",
                "provider": "people_data_labs",
            },
        )
        second = await client.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/another-person",
                "provider": "people_data_labs",
            },
        )
    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_concurrent_identical_requests_share_one_provider_call() -> None:
    upstream_calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        await asyncio.sleep(0.02)
        return httpx.Response(200, json=_payload())

    app = create_app(
        Settings(environment="test", pdl_api_key="test-key", cache_ttl_seconds=300),
        oidc_transport=httpx.MockTransport(handler),
    )
    request = {
        "profile_url": "https://www.linkedin.com/in/seanthorne",
        "provider": "people_data_labs",
    }
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        responses = await asyncio.gather(
            *(client.post("/v1/profiles/resolve", json=request) for _ in range(8))
        )

    assert upstream_calls == 1
    assert all(response.status_code == 200 for response in responses)
    assert sum(response.json()["meta"]["cached"] for response in responses) == 7
