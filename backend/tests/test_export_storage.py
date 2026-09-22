import json

import httpx
import pytest

from app.export import storage


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_upload_overwrites_and_authenticates():
    seen = {}

    def handler(request):
        seen.update(method=request.method, url=str(request.url),
                    upsert=request.headers.get("x-upsert"),
                    auth=request.headers.get("authorization"),
                    body=request.content)
        return httpx.Response(200, json={"Key": "exports/p/x.docx"})

    await storage.upload("p/x.docx", b"contenu", "application/pdf",
                         client=_client(handler))
    assert seen["method"] == "POST"
    assert seen["url"] == "http://storage.test/storage/v1/object/exports/p/x.docx"
    assert seen["upsert"] == "true"
    assert seen["auth"] == "Bearer cle-de-test"
    assert seen["body"] == b"contenu"


async def test_a_signed_url_is_absolute_and_short_lived():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["url"] = str(request.url)
        return httpx.Response(200, json={
            "signedURL": "/object/sign/exports/p/x.pdf?token=abc"})

    url = await storage.signed_url("p/x.pdf", client=_client(handler))
    assert seen["url"] == "http://storage.test/storage/v1/object/sign/exports/p/x.pdf"
    assert seen["body"] == {"expiresIn": storage.SIGNED_URL_SECONDS}
    assert url == ("http://storage.test/storage/v1"
                   "/object/sign/exports/p/x.pdf?token=abc")
    assert storage.SIGNED_URL_SECONDS <= 3600


async def test_a_storage_error_is_not_swallowed():
    """Un dépôt raté ne doit jamais laisser croire qu'un export existe."""
    def handler(request):
        return httpx.Response(403, json={"error": "denied"})

    with pytest.raises(httpx.HTTPStatusError):
        await storage.upload("p/x.docx", b"x", "application/pdf",
                             client=_client(handler))


async def test_deleting_a_prefix_lists_every_object_under_it():
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url),
                      json.loads(request.content) if request.content else None))
        if request.url.path.endswith("/object/list/exports"):
            return httpx.Response(200, json=[{"name": "a.docx"}, {"name": "a.pdf"}])
        return httpx.Response(200, json=[])

    await storage.delete_prefix("p", client=_client(handler))
    deletion = [c for c in calls if c[0] == "DELETE"]
    assert deletion and deletion[0][2] == {"prefixes": ["p/a.docx", "p/a.pdf"]}


@pytest.mark.network
async def test_the_real_bucket_round_trips():
    """La seule preuve que les détails de l'API REST sont les bons. Exige
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY et le bucket privé `exports`."""
    from app.core.config import settings

    # La configuration, pas `os.environ` : les clés vivent dans `backend/.env`,
    # que `pydantic-settings` lit sans le verser dans l'environnement du
    # processus. Tester `os.environ` faisait sauter ce test partout, y compris
    # quand le stockage était configuré — il ne prouvait donc jamais rien.
    settings.cache_clear()
    if not settings().supabase_url.startswith("https://"):
        pytest.skip("stockage Supabase non configuré")
    path = "essai-reseau/aller-retour.txt"
    await storage.upload(path, b"bonjour", "text/plain")
    url = await storage.signed_url(path)
    async with httpx.AsyncClient() as http:
        assert (await http.get(url)).content == b"bonjour"
    await storage.delete_prefix("essai-reseau")
