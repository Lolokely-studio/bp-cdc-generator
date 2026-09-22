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


async def test_a_failed_rendering_records_nothing(client, account, stored,
                                                  monkeypatch):
    """Gotenberg et le repli échouent tous deux : `render_pdf` lève (tâche 4).
    L'export s'arrête sans rien enregistrer ni déposer."""
    from app.export import service

    async def _no_pdf(*args, **kwargs):
        raise RuntimeError("ni Gotenberg ni le repli")

    monkeypatch.setattr(service, "render_pdf", _no_pdf)
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    await asyncio.sleep(1)
    body = (await client.get(f"/projects/{project_id}/exports",
                             headers=account)).json()
    assert body["fichiers"] == []
    assert stored == {}


async def test_a_failed_upload_records_nothing(client, account, monkeypatch):
    """Rien n'est enregistré pour un fichier qui n'a pas été déposé : une
    ligne `exports` ne doit jamais pointer vers le vide."""
    from app.export import storage

    async def _refuse(path, data, content_type, *, client=None):
        raise RuntimeError("stockage injoignable")

    monkeypatch.setattr(storage, "upload", _refuse)
    project_id = (await client.post("/projects", json=CREATION,
                                    headers=account)).json()["id"]
    await client.post(f"/projects/{project_id}/exports", headers=account)
    await asyncio.sleep(1)
    body = (await client.get(f"/projects/{project_id}/exports",
                             headers=account)).json()
    assert body["fichiers"] == []


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
