import hashlib

import httpx
import pytest

from profileproof.app import create_app
from profileproof.config import Settings


@pytest.mark.asyncio
async def test_health_and_readiness(client: httpx.AsyncClient) -> None:
    health = await client.get("/healthz")
    ready = await client.get("/readyz")
    assert health.json() == {"status": "ok", "version": "1.0.0", "environment": "test"}
    assert ready.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_landing_and_openapi(client: httpx.AsyncClient) -> None:
    landing = await client.get("/")
    schema = await client.get("/openapi.json")
    assert "ProfileProof API" in landing.text
    assert schema.json()["info"]["version"] == "1.0.0"
    assert "/v1/profiles/resolve" in schema.json()["paths"]


@pytest.mark.asyncio
async def test_demo_profile_end_to_end(client: httpx.AsyncClient) -> None:
    first = await client.post(
        "/v1/profiles/resolve",
        json={"profile_url": "https://linkedin.com/in/profileproof-demo?trk=test"},
        headers={"X-Request-ID": "test-request"},
    )
    second = await client.post(
        "/v1/profiles/resolve",
        json={"profile_url": "https://www.linkedin.com/in/profileproof-demo"},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["canonical_url"] == "https://www.linkedin.com/in/profileproof-demo"
    assert payload["profile"]["name"] == "Aarav Mehta"
    assert payload["source"]["mode"] == "synthetic_demo"
    assert payload["meta"]["warnings"] == ["demo_data"]
    assert payload["meta"]["completeness"] == 0.9
    assert first.headers["x-request-id"] == "test-request"
    assert second.json()["meta"]["cached"] is True


@pytest.mark.asyncio
async def test_arbitrary_demo_url_fails_honestly(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/profiles/resolve",
        json={"profile_url": "https://www.linkedin.com/in/real-person"},
    )
    assert response.status_code == 424
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "does not scrape" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_url_is_problem_details(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/profiles/resolve", json={"profile_url": "http://127.0.0.1/admin"}
    )
    assert response.status_code == 422
    assert response.json()["title"] == "Invalid LinkedIn profile URL"
    assert response.json()["request_id"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_request_validation_uses_problem_details(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/profiles/resolve", json={"unexpected": True})
    assert response.status_code == 422
    assert response.json()["type"].endswith("/validation")


@pytest.mark.asyncio
async def test_consented_profile_is_normalized_without_persistence(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/v1/profiles/resolve",
        json={
            "profile_url": "https://www.linkedin.com/in/owner-supplied",
            "provider": "consented",
            "consented_profile": {
                "name": "Owner Supplied",
                "headline": "Principal Engineer",
                "skills": [" Python ", "Python", "Go"],
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["profile"]["skills"] == ["Python", "Go"]
    assert response.json()["source"]["consented"] is True
    assert response.json()["meta"]["cached"] is False


@pytest.mark.asyncio
async def test_security_headers_are_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_metrics_have_bounded_labels(client: httpx.AsyncClient) -> None:
    await client.post(
        "/v1/profiles/resolve",
        json={"profile_url": "https://www.linkedin.com/in/profileproof-demo"},
    )
    response = await client.get("/metrics")
    assert "profileproof_provider_calls_total" in response.text
    assert 'provider="demo",outcome="success"' in response.text


@pytest.mark.asyncio
async def test_api_key_guard() -> None:
    digest = hashlib.sha256(b"correct-key").hexdigest()
    app = create_app(Settings(environment="test", api_key_sha256=digest))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as guarded,
    ):
        denied = await guarded.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/profileproof-demo"},
        )
        allowed = await guarded.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/profileproof-demo"},
            headers={"X-API-Key": "correct-key"},
        )
    assert denied.status_code == 401
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit() -> None:
    app = create_app(Settings(environment="test", rate_limit_requests=1))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as limited,
    ):
        assert (
            await limited.post(
                "/v1/profiles/resolve",
                json={"profile_url": "https://www.linkedin.com/in/profileproof-demo"},
            )
        ).status_code == 200
        rejected = await limited.post(
            "/v1/profiles/resolve",
            json={"profile_url": "https://www.linkedin.com/in/profileproof-demo"},
        )
    assert rejected.status_code == 429
    assert int(rejected.headers["retry-after"]) >= 1


@pytest.mark.asyncio
async def test_body_size_limit() -> None:
    app = create_app(Settings(environment="test", max_body_bytes=1024))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as limited,
    ):
        response = await limited.post(
            "/v1/profiles/resolve",
            content=b"x" * 1025,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
