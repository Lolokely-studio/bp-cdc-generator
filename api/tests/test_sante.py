import httpx
import pytest
from esquisse.app import creer_app


async def test_sante_repond_ok():
    app = creer_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/health")
    assert reponse.status_code == 200
    assert reponse.json() == {"statut": "ok"}
