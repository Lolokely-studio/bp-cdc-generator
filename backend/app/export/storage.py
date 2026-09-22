import httpx

from app.core.config import settings

# Dix minutes. Un lien signé circule : on le veut assez long pour cliquer,
# assez court pour qu'un lien copié ailleurs ne serve plus le lendemain.
SIGNED_URL_SECONDS = 600


def _base() -> str:
    return f"{settings().supabase_url.rstrip('/')}/storage/v1"


def _checked(path: str) -> str:
    """Refuse un chemin qui sortirait du bucket.

    httpx normalise `..` AVANT d'envoyer la requête : `p/../../autre/x.pdf`
    devient `/storage/v1/autre/x.pdf`, hors de `object/` et du bucket. `?` et
    `#` coupent aussi le chemin. Aujourd'hui les chemins sont fabriqués par le
    code — un UUID et des littéraux — donc rien n'est exploitable ; ce garde
    tient pour le jour où un segment viendrait d'une saisie.
    """
    segments = path.split("/")
    if any(s in ("", ".", "..") for s in segments) or any(c in path for c in "?#"):
        raise ValueError(f"chemin de stockage refusé : {path!r}")
    return path


def _headers() -> dict[str, str]:
    key = settings().supabase_service_role_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


async def _call(method: str, url: str, client: httpx.AsyncClient | None, **kwargs):
    owned = client is None
    http = client or httpx.AsyncClient(timeout=60)
    try:
        response = await http.request(method, url, headers={**_headers(),
                                      **kwargs.pop("headers", {})}, **kwargs)
        # Jamais avalée : un dépôt raté qui passerait en silence laisserait
        # une ligne `exports` pointer vers un fichier qui n'existe pas.
        response.raise_for_status()
        return response
    finally:
        if owned:
            await http.aclose()


async def upload(path: str, data: bytes, content_type: str, *, client=None) -> None:
    bucket = settings().supabase_bucket_name
    await _call("POST", f"{_base()}/object/{bucket}/{_checked(path)}", client,
                content=data,
                headers={"Content-Type": content_type, "x-upsert": "true"})


async def signed_url(path: str, *, client=None) -> str:
    bucket = settings().supabase_bucket_name
    response = await _call("POST", f"{_base()}/object/sign/{bucket}/{_checked(path)}",
                           client, json={"expiresIn": SIGNED_URL_SECONDS})
    # Le chemin rendu est RELATIF à `/storage/v1`.
    return f"{_base()}{response.json()['signedURL']}"


async def delete_prefix(prefix: str, *, client=None) -> None:
    """Supprime tout ce qui est rangé sous `prefix`.

    L'API supprime des chemins exacts, pas un préfixe : on liste d'abord.
    Sert à la suppression d'un projet, qui doit emporter ses exports (§9.3).
    """
    bucket = settings().supabase_bucket_name
    _checked(prefix)
    listing = await _call("POST", f"{_base()}/object/list/{bucket}", client,
                          json={"prefix": prefix, "limit": 1000})
    names = [f"{prefix}/{item['name']}" for item in listing.json()]
    if names:
        await _call("DELETE", f"{_base()}/object/{bucket}", client,
                    json={"prefixes": names})
