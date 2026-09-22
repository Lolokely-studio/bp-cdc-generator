import httpx

from app.agent.state import Paragraph, Table
from app.export.document import ExportDocument, ExportSection
from app.export.html import render_html
from app.export.pdf import render_pdf

_PDF = b"%PDF"


def _document():
    return ExportDocument(
        document="cdc", title="Cahier des charges — CoachDom", draft=True,
        missing=["budget"],
        sections=[ExportSection("Contexte", [
            Paragraph(text="Une phrase <avec> des chevrons & une esperluette."),
            Table(number=1, title="Planning", columns=["Étape"], rows=[["Lancement"]]),
        ])],
    )


def _gotenberg(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                             base_url="http://gotenberg.test")


def test_the_html_escapes_what_it_quotes():
    """Le texte rédigé est du texte, jamais du balisage."""
    html = render_html(_document(), [])
    assert "&lt;avec&gt;" in html
    assert "<avec>" not in html


def test_the_html_escapes_the_title():
    """Le titre porte le nom du projet, du texte libre : un « & » y a déjà
    fait planter le Word (tâche 3), le HTML ne doit pas y être vulnérable non
    plus."""
    document = ExportDocument(document="cdc",
                              title="CDC — Tom & <Jerry>",
                              sections=[])
    html = render_html(document, [])
    assert "&amp;" in html
    assert "&lt;Jerry&gt;" in html
    assert "Tom & <Jerry>" not in html


def test_the_html_carries_the_draft_notice_and_the_appendix():
    html = render_html(_document(), [])
    assert "Brouillon" in html
    assert "Données à compléter" in html
    assert "Tableau 1 — Planning" in html


async def test_gotenberg_converts_and_the_pdf_is_faithful(monkeypatch):
    from app.core import config

    monkeypatch.setenv("GOTENBERG_URL", "http://gotenberg.test")
    monkeypatch.setenv("GOTENBERG_USERNAME", "esquisse")
    monkeypatch.setenv("GOTENBERG_PASSWORD", "secret")
    config.settings.cache_clear()
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"%PDF-1.7 converti")

    try:
        result = await render_pdf(b"word", _document(), [],
                                  client=_gotenberg(handler))
    finally:
        config.settings.cache_clear()
    assert result.faithful is True
    assert result.data.startswith(_PDF)
    assert seen["path"] == "/forms/libreoffice/convert"
    assert seen["auth"] and seen["auth"].startswith("Basic ")


async def test_a_failing_gotenberg_falls_back_and_says_so(monkeypatch):
    from app.core import config

    monkeypatch.setenv("GOTENBERG_URL", "http://gotenberg.test")
    config.settings.cache_clear()

    def handler(request):
        return httpx.Response(503)

    try:
        result = await render_pdf(b"word", _document(), [],
                                  client=_gotenberg(handler))
    finally:
        config.settings.cache_clear()
    assert result.faithful is False
    assert result.data.startswith(_PDF)


async def test_a_gotenberg_that_never_answers_falls_back(monkeypatch):
    from app.core import config

    monkeypatch.setenv("GOTENBERG_URL", "http://gotenberg.test")
    config.settings.cache_clear()

    def handler(request):
        raise httpx.ConnectTimeout("endormi", request=request)

    try:
        result = await render_pdf(b"word", _document(), [],
                                  client=_gotenberg(handler))
    finally:
        config.settings.cache_clear()
    assert result.faithful is False


async def test_without_gotenberg_configured_the_fallback_is_used_directly():
    """L'URL vide vaut « pas de Gotenberg » : c'est l'état de toute la suite
    de tests, fixé par conftest."""
    result = await render_pdf(b"word", _document(), [])
    assert result.faithful is False
    assert result.data.startswith(_PDF)


async def test_without_gotenberg_configured_it_is_never_contacted(monkeypatch):
    """Renforce le test précédent : une URL vide ne doit pas seulement finir
    en repli, elle ne doit jamais faire parler à Gotenberg. Un code qui
    tenterait quand même l'appel échouerait vite (URL invalide) et retomberait
    au même résultat par accident — ce qui masquerait la régression si l'on
    ne vérifiait que `faithful` et `data`."""
    from app.core import config

    monkeypatch.setenv("GOTENBERG_URL", "")
    config.settings.cache_clear()

    def handler(request):
        raise AssertionError("Gotenberg ne doit pas être joint quand "
                             "l'URL n'est pas configurée")

    try:
        result = await render_pdf(b"word", _document(), [],
                                  client=_gotenberg(handler))
    finally:
        config.settings.cache_clear()
    assert result.faithful is False
    assert result.data.startswith(_PDF)
