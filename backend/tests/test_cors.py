import httpx

from app.core import config
from app.main import create_app

_PREFLIGHT = {"Access-Control-Request-Method": "POST",
              "Access-Control-Request-Headers": "authorization,content-type"}


async def _preflight(origin: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.options("/projects", headers={"Origin": origin, **_PREFLIGHT})


async def test_the_declared_front_may_call_the_api(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://esquisse.vercel.app/, http://localhost:3001")
    config.settings.cache_clear()
    try:
        response = await _preflight("https://esquisse.vercel.app")
    finally:
        config.settings.cache_clear()
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://esquisse.vercel.app"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


async def test_another_origin_gets_no_cors_header(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://esquisse.vercel.app")
    config.settings.cache_clear()
    try:
        response = await _preflight("https://ailleurs.example")
    finally:
        config.settings.cache_clear()
    assert "access-control-allow-origin" not in response.headers
