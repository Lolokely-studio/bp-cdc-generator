import asyncio

import pytest
import pytest_asyncio

from tests.test_project_routes import CREATION, _active_account


@pytest_asyncio.fixture(autouse=True)
async def _fake_llm(monkeypatch):
    """Obligatoire dans tout fichier qui appelle `POST /projects` : voir
    `tests/test_project_routes.py::_fake_llm`."""
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config

    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest_asyncio.fixture
async def account(client, migrated_db):
    return await _active_account(client, "exports")


@pytest.fixture
def stored(monkeypatch):
    """Un stockage en mémoire, à la place de Supabase."""
    from app.export import storage

    files = {}

    async def _upload(path, data, content_type, *, client=None):
        files[path] = (data, content_type)

    async def _signed_url(path, *, client=None):
        return f"https://signe.test/{path}?token=x"

    monkeypatch.setattr(storage, "upload", _upload)
    monkeypatch.setattr(storage, "signed_url", _signed_url)
    return files


async def _wait_for_files(client, project_id, headers):
    for _ in range(200):
        body = (await client.get(f"/projects/{project_id}/exports",
                                 headers=headers)).json()
        if not body["en_cours"] and body["fichiers"]:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("l'export n'a jamais déposé de fichier")


async def _wait_until_done(client, project_id, headers):
    """Attend la fin réelle de l'export. `start_export` inscrit la tâche avant
    de rendre la main, donc `en_cours` est vrai dès la réponse au POST."""
    for _ in range(400):
        body = (await client.get(f"/projects/{project_id}/exports",
                                 headers=headers)).json()
        if not body["en_cours"]:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("l'export ne s'est jamais terminé")


CREATION_BP = {**CREATION, "documents": "bp", "profil_cdc": None,
              "profil_bp": "banque"}
_WORD_TYPE = ("application/vnd.openxmlformats-officedocument."
             "wordprocessingml.document")


async def test_an_export_deposits_a_word_and_a_pdf(client, account, stored):
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    response = await client.post(f"/projects/{project_id}/exports", headers=account)
    assert response.status_code == 202

    body = await _wait_for_files(client, project_id, account)
    formats = {(f["document"], f["format"]) for f in body["fichiers"]}
    assert formats == {("cdc", "docx"), ("cdc", "pdf")}
    assert set(stored) == {f"{project_id}/cdc.docx", f"{project_id}/cdc.pdf"}
    assert stored[f"{project_id}/cdc.pdf"][0].startswith(b"%PDF")


async def test_an_unfinished_project_is_exported_as_a_draft(client, account, stored):
    """Aucune section n'est écrite à la création : le document est un
    brouillon, et le dit."""
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_for_files(client, project_id, account)
    assert all(f["brouillon"] for f in body["fichiers"])


async def test_the_fallback_pdf_is_reported_as_not_faithful(client, account, stored):
    """Sans Gotenberg, le PDF vient du repli, et l'utilisateur le sait."""
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_for_files(client, project_id, account)
    pdf = next(f for f in body["fichiers"] if f["format"] == "pdf")
    docx = next(f for f in body["fichiers"] if f["format"] == "docx")
    assert pdf["fidele"] is False
    assert docx["fidele"] is True


async def test_every_listing_signs_fresh_links(client, account, stored):
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_for_files(client, project_id, account)
    assert all(f["lien"].startswith("https://signe.test/") for f in body["fichiers"])


async def test_a_second_export_while_one_runs_is_refused(client, account,
                                                         stored, monkeypatch):
    from app.export import service

    monkeypatch.setattr(service, "is_exporting", lambda project_id: True)
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    response = await client.post(f"/projects/{project_id}/exports", headers=account)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "export_deja_en_cours"}}


async def test_another_users_exports_are_not_found(client, account, stored):
    owner = await _active_account(client, "exports-proprio")
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=owner)).json()["id"]
    for method in ("post", "get"):
        response = await getattr(client, method)(
            f"/projects/{project_id}/exports", headers=account)
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "projet_introuvable"}}


async def test_a_failed_upload_records_nothing(client, account, stored, monkeypatch):
    """Le stockage signe pour de faux (`stored`) : si une ligne était écrite,
    la liste la montrerait, et c'est l'assertion du test qui tomberait — pas
    une erreur de connexion par accident."""
    from app.export import storage

    async def _refuse(path, data, content_type, *, client=None):
        raise RuntimeError("stockage injoignable")

    monkeypatch.setattr(storage, "upload", _refuse)
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_until_done(client, project_id, account)
    assert body["fichiers"] == []
    assert body["dernier_export"] == "echec"


async def test_a_failed_rendering_records_nothing(client, account, stored,
                                                  monkeypatch):
    from app.export import service

    async def _no_pdf(*args, **kwargs):
        raise RuntimeError("ni Gotenberg ni le repli")

    monkeypatch.setattr(service, "render_pdf", _no_pdf)
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_until_done(client, project_id, account)
    assert body["fichiers"] == []
    assert stored == {}
    assert body["dernier_export"] == "echec"


async def test_a_successful_export_says_so(client, account, stored):
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_until_done(client, project_id, account)
    assert body["dernier_export"] == "ok"


async def test_a_failed_export_leaves_the_previous_one_untouched(
        client, account, stored, monkeypatch):
    """Tout rendre avant de rien déposer : un rendu raté ne touche ni au
    stockage ni aux lignes de l'export précédent."""
    from app.export import service

    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    before = await _wait_until_done(client, project_id, account)
    stored_before = dict(stored)

    async def _no_pdf(*args, **kwargs):
        raise RuntimeError("panne")

    monkeypatch.setattr(service, "render_pdf", _no_pdf)
    await client.post(f"/projects/{project_id}/exports", headers=account)
    after = await _wait_until_done(client, project_id, account)
    assert after["fichiers"] == before["fichiers"]
    assert stored == stored_before
    assert after["dernier_export"] == "echec"


async def test_a_failure_on_one_document_does_not_deposit_the_others(
        client, account, stored, monkeypatch):
    """Invention (tour 2) : « tout rendre puis tout déposer » vaut aussi
    ENTRE les documents d'un export « both ». `test_a_failed_export_leaves_
    the_previous_one_untouched` n'exerce qu'un seul document — un rendu
    identique produit des octets identiques, donc comparer `stored` avant et
    après ne distingue pas « rien déposé » de « déposé, mais pareil ». Le
    compte d'appels à `storage.upload`, lui, ne ment pas."""
    from app.export import service, storage
    from app.export.pdf import render_pdf as real_render_pdf

    creation = {**CREATION, "nom": "LesDeux", "documents": "both",
               "profil_bp": "banque"}
    project_id = (await client.post("/projects", json=creation,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    before = await _wait_until_done(client, project_id, account)

    calls = []
    real_upload = storage.upload

    async def _spy_upload(path, data, content_type, *, client=None):
        calls.append(path)
        await real_upload(path, data, content_type, client=client)

    async def _fail_on_bp(word, document, charts, **kwargs):
        if document.document == "bp":
            raise RuntimeError("panne sur le second document")
        return await real_render_pdf(word, document, charts, **kwargs)

    monkeypatch.setattr(storage, "upload", _spy_upload)
    monkeypatch.setattr(service, "render_pdf", _fail_on_bp)
    await client.post(f"/projects/{project_id}/exports", headers=account)
    after = await _wait_until_done(client, project_id, account)

    assert calls == [], (
        "le premier document ne doit rien déposer tant que le second n'a "
        "pas fini de se rendre"
    )
    assert after["fichiers"] == before["fichiers"]
    assert after["dernier_export"] == "echec"


async def test_exporting_twice_keeps_one_row_per_file(client, account, stored):
    """`dernier_export` est vérifié à CHAQUE tour, pas seulement le compte de
    fichiers à la fin : sans `on conflict`, le second export lève une
    violation de l'index unique, la transaction est annulée dans son
    intégralité, et les deux lignes du premier export survivent par
    accident — un test qui ne regarderait que leur nombre resterait vert
    alors que le second export a échoué."""
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    for _ in range(2):
        await client.post(f"/projects/{project_id}/exports", headers=account)
        body = await _wait_until_done(client, project_id, account)
        assert body["dernier_export"] == "ok"
    assert len(body["fichiers"]) == 2


async def test_files_are_stored_with_their_content_type(client, account, stored):
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    await _wait_until_done(client, project_id, account)
    assert stored[f"{project_id}/cdc.docx"][1] == _WORD_TYPE
    assert stored[f"{project_id}/cdc.pdf"][1] == "application/pdf"


async def test_each_link_signs_its_own_file(client, account, stored):
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_until_done(client, project_id, account)
    for f in body["fichiers"]:
        assert f"{project_id}/{f['document']}.{f['format']}" in f["lien"]


async def test_a_finished_project_is_not_a_draft(client, account, stored):
    """Toutes les sections `done` : le document n'est pas un brouillon. Sans
    ce test, `brouillon` figé à vrai passait, puisque tous les autres
    exportent un projet sans section."""
    from uuid import UUID

    from app.agent.projections import save_section
    from app.agent.state import Paragraph
    from app.agent.templates import load_catalogue
    from app.core.db import connection

    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    async with connection() as conn:
        for ref in load_catalogue().plan_for("cdc", "consultation", None):
            await save_section(conn, UUID(project_id), ref,
                               blocks=[Paragraph(text="x")], statut="done",
                               note=9, revisions=0)
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_until_done(client, project_id, account)
    assert body["fichiers"] and not any(f["brouillon"] for f in body["fichiers"])


async def test_a_business_plan_export_embeds_its_charts(client, account, stored,
                                                        monkeypatch):
    """Les calculs viennent du point de reprise ; un `_computations` vide
    passait inaperçu."""
    import io

    from docx import Document

    from app.agent.finance import IncomeAssumptions, income_statement_3y
    from app.export import service

    income = income_statement_3y(IncomeAssumptions(
        first_year_revenue=100_000, gross_margin_rate=0.6, fixed_costs=30_000,
        depreciation=5_000, annual_growth=0.1))

    asked = []

    async def _computations(thread_id):
        asked.append(thread_id)
        return {"compte_resultat_3ans": income}

    monkeypatch.setattr(service, "_computations", _computations)
    project_id = (await client.post("/projects", json=CREATION_BP,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    await _wait_until_done(client, project_id, account)
    word = Document(io.BytesIO(stored[f"{project_id}/bp.docx"][0]))
    # Le fil du projet, et pas son identifiant : un mauvais argument ici
    # rendrait un point de reprise vide, donc aucun graphique dans aucun
    # business plan — et en silence, puisqu'un calcul absent ne lève pas.
    from uuid import UUID

    from app.core.db import connection

    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select thread_id from projects where id = %s",
                              (UUID(project_id),))
            thread_id = (await cur.fetchone())[0]
    assert asked == [thread_id]
    assert len(word.inline_shapes) >= 1


async def test_a_finished_export_never_unregisters_its_successor():
    """La leçon du registre des runs (plan 4, tâche 3), appliquée aux
    exports : le rappel de fin ne retire que SA propre tâche. On le déclenche
    à la main après le remplacement, plutôt que de compter sur l'ordonnanceur
    pour ouvrir la fenêtre de course."""
    from app.export import service

    async def _long():
        await asyncio.sleep(10)

    first = asyncio.create_task(asyncio.sleep(0))
    service._exports["projet-course"] = first
    await first
    second = asyncio.create_task(_long())
    service._exports["projet-course"] = second
    try:
        service._forget_callback("projet-course")(first)
        assert service.is_exporting("projet-course")
    finally:
        await service.cancel_all()


async def test_both_documents_are_recorded_under_their_own_name(client, account, stored):
    """Invention de la tâche : un projet « both » exporte deux documents.
    Si l'un des deux s'enregistrait sous le nom de l'autre, une ligne
    écraserait l'autre en base malgré deux chemins de stockage distincts."""
    creation = {**CREATION, "nom": "LesDeux", "documents": "both",
               "profil_bp": "banque"}
    project_id = (await client.post("/projects", json=creation,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    body = await _wait_for_files(client, project_id, account)
    formats = {(f["document"], f["format"]) for f in body["fichiers"]}
    assert formats == {("cdc", "docx"), ("cdc", "pdf"),
                       ("bp", "docx"), ("bp", "pdf")}


async def test_a_project_listing_never_signs_another_projects_paths(client, account, stored):
    """Invention de la tâche : deux projets du même compte. La liste du
    premier ne doit rendre que ses propres chemins, jamais ceux du second."""
    first_id = (await client.post("/projects", json=CREATION,
                                  headers=account)).json()["id"]
    await client.post(f"/projects/{first_id}/exports", headers=account)
    await _wait_for_files(client, first_id, account)

    second_creation = {**CREATION, "nom": "Deuxieme"}
    second_id = (await client.post("/projects", json=second_creation,
                                   headers=account)).json()["id"]
    await client.post(f"/projects/{second_id}/exports", headers=account)
    await _wait_for_files(client, second_id, account)

    body = (await client.get(f"/projects/{first_id}/exports",
                             headers=account)).json()
    assert all(f["lien"].startswith(f"https://signe.test/{first_id}/")
              for f in body["fichiers"])
    assert len(body["fichiers"]) == 2


async def test_computations_are_read_from_the_checkpoint(monkeypatch):
    """Le corps de `_computations`, et non une doublure qui le remplace.

    Le test des graphiques remplace la fonction entière : son corps n'était
    exécuté par aucun test, et rendre `{}` y passait inaperçu. On fournit ici
    un graphe dont l'état porte des calculs, et on vérifie qu'ils sortent —
    y compris quand l'état n'en porte aucun.
    """
    from types import SimpleNamespace

    from app.export import service

    class _Graph:
        def __init__(self, values):
            self.values = values
            self.asked = None

        async def aget_state(self, config):
            self.asked = config
            return SimpleNamespace(values=self.values)

    graph = _Graph({"computations": {"tam_sam_som": {"numbers": [1.0]}}})

    async def _compiled():
        return graph

    monkeypatch.setattr(service, "compiled_graph", _compiled)
    assert await service._computations("fil-x") == {
        "tam_sam_som": {"numbers": [1.0]}}
    assert graph.asked == {"configurable": {"thread_id": "fil-x"}}

    graph.values = {}
    assert await service._computations("fil-x") == {}
    graph.values = None
    assert await service._computations("fil-x") == {}



async def test_a_re_export_after_completion_clears_the_draft_flag(client, account,
                                                                  stored):
    """Exporté en brouillon, puis réexporté une fois toutes les sections
    `done` : les lignes doivent perdre `brouillon`. Retirer `brouillon` de la
    clause `on conflict do update` laissait la suite verte, puisque les autres
    tests réexportent un état identique."""
    from uuid import UUID

    from app.agent.projections import save_section
    from app.agent.state import Paragraph
    from app.agent.templates import load_catalogue
    from app.core.db import connection

    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    first = await _wait_until_done(client, project_id, account)
    assert all(f["brouillon"] for f in first["fichiers"])

    async with connection() as conn:
        for ref in load_catalogue().plan_for("cdc", "consultation", None):
            await save_section(conn, UUID(project_id), ref,
                               blocks=[Paragraph(text="x")], statut="done",
                               note=9, revisions=0)
    relaunched = await client.post(f"/projects/{project_id}/exports", headers=account)
    assert relaunched.status_code == 202, relaunched.json()
    second = await _wait_until_done(client, project_id, account)
    assert second["dernier_export"] == "ok", second
    assert second["fichiers"] and not any(f["brouillon"] for f in second["fichiers"]), second
