import httpx
import pytest
from esquisse.app import create_app


async def test_health_returns_ok():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/health")
    assert reponse.status_code == 200
    assert reponse.json() == {"statut": "ok"}
