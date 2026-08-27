from collections.abc import AsyncIterator

import httpx
import pytest_asyncio

from profileproof.app import create_app
from profileproof.config import Settings


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(
            environment="test",
            rate_limit_requests=1000,
            cache_ttl_seconds=300,
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as test_client,
    ):
        yield test_client
