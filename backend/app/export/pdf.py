import asyncio
import io
import logging
from dataclasses import dataclass

import httpx
from xhtml2pdf import pisa

from app.core.config import settings
from app.export.charts import Chart
from app.export.document import ExportDocument
from app.export.html import render_html

logger = logging.getLogger(__name__)

_CONVERT_PATH = "/forms/libreoffice/convert"


@dataclass
class PdfResult:
    data: bytes
    # Vrai quand Gotenberg a converti le Word lui-même. Faux quand le PDF
    # vient du repli HTML : les deux fichiers disent alors la même chose sans
    # se ressembler, et la spec veut que l'utilisateur le sache (§7).
    faithful: bool


async def _convert_with_gotenberg(word: bytes, client: httpx.AsyncClient) -> bytes:
    config = settings()
    auth = None
    if config.gotenberg_username:
        auth = (config.gotenberg_username, config.gotenberg_password)
    response = await client.post(
        _CONVERT_PATH,
        files={"files": ("document.docx", word,
                         "application/vnd.openxmlformats-officedocument."
                         "wordprocessingml.document")},
        auth=auth,
        timeout=config.gotenberg_timeout_seconds,
    )
    response.raise_for_status()
    return response.content


def _fallback(document: ExportDocument, charts: list[Chart]) -> bytes:
    output = io.BytesIO()
    status = pisa.CreatePDF(render_html(document, charts), dest=output,
                            encoding="utf-8")
    if status.err:
        raise RuntimeError("le repli HTML n'a pas produit de PDF")
    return output.getvalue()


async def render_pdf(word: bytes, document: ExportDocument, charts: list[Chart],
                     *, client: httpx.AsyncClient | None = None) -> PdfResult:
    """Gotenberg d'abord, le repli ensuite, et jamais en silence.

    Toute erreur de Gotenberg — service endormi qui ne se réveille pas à
    temps, 503, mémoire insuffisante sur les 512 Mo de l'offre gratuite —
    mène au repli. Le repli rend `faithful=False`, que l'appelant enregistre et
    montre à l'utilisateur.

    `client` n'est renseigné que par les tests. En production on en ouvre un
    le temps de l'appel : un export est rare, garder une connexion ouverte
    vers un service qui dort n'a pas de sens.
    """
    config = settings()
    if config.gotenberg_url:
        owned = client is None
        http = client or httpx.AsyncClient(base_url=config.gotenberg_url)
        try:
            return PdfResult(await _convert_with_gotenberg(word, http), True)
        except (httpx.HTTPError, OSError) as error:
            logger.warning("Gotenberg indisponible, repli HTML : %s", error)
        finally:
            if owned:
                await http.aclose()
    # `xhtml2pdf` est synchrone et prend un peu de temps processeur : il sort
    # de la boucle d'événements pour ne pas figer les runs qui avancent.
    data = await asyncio.to_thread(_fallback, document, charts)
    return PdfResult(data, False)
