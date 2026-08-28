import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest

from profileproof.app import create_app
from profileproof.config import Settings


@pytest.mark.asyncio
async def test_health_and_readiness(client: httpx.AsyncClient) -> None:
    health = await client.get("/health")
    ready = await client.get("/readyz")
    assert health.json() == {"status": "ok", "version": "1.1.0", "environment": "test"}
    assert ready.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_landing_and_openapi(client: httpx.AsyncClient) -> None:
    landing = await client.get("/")
    script = await client.get("/static/app.js")
    stylesheet = await client.get("/static/app.css")
    favicon = await client.get("/static/favicon.svg")
    schema = await client.get("/openapi.json")
    assert "Professional profile intelligence" in landing.text
    assert 'role="tablist"' in landing.text
    assert 'aria-live="polite"' in landing.text
    assert "renderProfile" in script.text
    assert "@media (max-width: 680px)" in stylesheet.text
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert schema.json()["info"]["version"] == "1.1.0"
    assert "/v1/profiles/resolve" in schema.json()["paths"]


@pytest.mark.asyncio
async def test_documentation_assets_are_pinned_and_csp_is_scoped(
    client: httpx.AsyncClient,
) -> None:
    landing = await client.get("/")
    docs = await client.get("/docs")
    redoc = await client.get("/redoc")

    assert "unsafe-inline" not in landing.headers["content-security-policy"]
    assert "swagger-ui-dist@5.32.14" in docs.text
    assert "redoc@2.5.3" in redoc.text
    assert "https://cdn.jsdelivr.net" in docs.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_capabilities_do_not_expose_secrets(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/capabilities")
    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()["providers"]}
    assert set(providers) == {"linkedin_direct", "demo"}
    assert providers["linkedin_direct"]["real_data"] is True
    assert "secret" not in response.text.casefold()


@pytest.mark.asyncio
async def test_demo_profile_end_to_end(client: httpx.AsyncClient) -> None:
    first = await client.post(
        "/v1/profiles/resolve",
        json={
            "profile_url": "https://linkedin.com/in/profileproof-demo?trk=test",
            "provider": "demo",
        },
        headers={"X-Request-ID": "test-request"},
    )
    second = await client.post(
        "/v1/profiles/resolve",
        json={"profile_url": "https://www.linkedin.com/in/profileproof-demo", "provider": "demo"},
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
        json={"profile_url": "https://www.linkedin.com/in/real-person", "provider": "demo"},
    )
    assert response.status_code == 424
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "synthetic fixture" in response.json()["detail"]


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
async def test_security_headers_are_present(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.asyncio
async def test_metrics_have_bounded_labels(client: httpx.AsyncClient) -> None:
    await client.post(
        "/v1/profiles/resolve",
        json={"profile_url": "https://www.linkedin.com/in/profileproof-demo", "provider": "demo"},
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
            json={
                "profile_url": "https://www.linkedin.com/in/profileproof-demo",
                "provider": "demo",
            },
        )
        allowed = await guarded.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/profileproof-demo",
                "provider": "demo",
            },
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
                json={
                    "profile_url": "https://www.linkedin.com/in/profileproof-demo",
                    "provider": "demo",
                },
            )
        ).status_code == 200
        rejected = await limited.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/profileproof-demo",
                "provider": "demo",
            },
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


@pytest.mark.asyncio
async def test_streamed_body_size_limit_cannot_be_bypassed() -> None:
    app = create_app(Settings(environment="test", max_body_bytes=1024))

    async def body_chunks() -> AsyncIterator[bytes]:
        yield b"x" * 600
        yield b"y" * 600

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as limited,
    ):
        response = await limited.post(
            "/v1/profiles/resolve",
            content=body_chunks(),
            headers={"content-type": "application/json", "x-request-id": "stream-limit"},
        )
    assert response.status_code == 413
    assert response.headers["x-request-id"] == "stream-limit"
    assert response.headers["content-type"].startswith("application/problem+json")
