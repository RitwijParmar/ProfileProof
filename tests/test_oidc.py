import httpx
import pytest

from profileproof.app import create_app
from profileproof.config import Settings


@pytest.mark.asyncio
async def test_oidc_maps_official_lite_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.linkedin.com/v2/userinfo"
        assert request.headers["authorization"] == "Bearer owner-token"
        return httpx.Response(
            200,
            json={
                "sub": "member-id",
                "name": "Ada Lovelace",
                "picture": "https://media.licdn.com/example.jpg",
            },
        )

    app = create_app(Settings(environment="test"), oidc_transport=httpx.MockTransport(handler))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/owner-profile",
                "provider": "linkedin_oidc",
            },
            headers={"Authorization": "Bearer owner-token"},
        )
    assert response.status_code == 200
    assert response.json()["profile"]["name"] == "Ada Lovelace"
    assert response.json()["source"]["mode"] == "official_oidc_self_profile"


@pytest.mark.asyncio
async def test_oidc_requires_token(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/profiles/resolve",
        json={
            "profile_url": "https://www.linkedin.com/in/owner-profile",
            "provider": "linkedin_oidc",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_oidc_rejects_invalid_token(status: int) -> None:
    app = create_app(
        Settings(environment="test"),
        oidc_transport=httpx.MockTransport(lambda _request: httpx.Response(status)),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/owner-profile",
                "provider": "linkedin_oidc",
            },
            headers={"Authorization": "Bearer invalid"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_oidc_handles_bad_upstream_json() -> None:
    app = create_app(
        Settings(environment="test"),
        oidc_transport=httpx.MockTransport(lambda _request: httpx.Response(200, text="not-json")),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/owner-profile",
                "provider": "linkedin_oidc",
            },
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 502


@pytest.mark.asyncio
async def test_oidc_rejects_invalid_picture_url() -> None:
    app = create_app(
        Settings(environment="test"),
        oidc_transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"name": "Owner", "picture": "file:///tmp/x"})
        ),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/v1/profiles/resolve",
            json={
                "profile_url": "https://www.linkedin.com/in/owner-profile",
                "provider": "linkedin_oidc",
            },
            headers={"Authorization": "Bearer token"},
        )
    assert response.status_code == 502
