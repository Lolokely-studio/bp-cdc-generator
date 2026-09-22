import asyncio
import logging
from uuid import UUID

from app.agent.graph import compiled_graph
from app.agent.projections import load_sections
from app.agent.templates import load_catalogue
from app.core.db import connection
from app.export import storage
from app.export.charts import charts_for
from app.export.document import assemble
from app.export.pdf import render_pdf
from app.export.word import render_word
from app.projects.repository import record_export

logger = logging.getLogger(__name__)

_WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Un export en cours par projet. En mémoire du processus, comme le registre
# des runs, et pour la même raison (§9.2, une seule instance).
_exports: dict[str, asyncio.Task] = {}


class ExportAlreadyRunning(RuntimeError):
    """Un export tourne déjà pour ce projet."""


def is_exporting(project_id: str) -> bool:
    task = _exports.get(project_id)
    return task is not None and not task.done()


def start_export(project: dict) -> None:
    project_id = str(project["id"])
    if is_exporting(project_id):
        raise ExportAlreadyRunning(project_id)
    task = asyncio.create_task(export_project(project))
    _exports[project_id] = task
    # L'identité, pas la clé : c'est la leçon du registre des runs (plan 4,
    # tâche 3). Un export relancé dans l'intervalle ne doit pas voir son
    # entrée effacée par la fin du précédent.
    task.add_done_callback(_forget_callback(project_id))


def _forget_callback(project_id: str):
    def _forget(finished: asyncio.Task) -> None:
        if _exports.get(project_id) is finished:
            del _exports[project_id]
    return _forget


async def _computations(thread_id: str) -> dict:
    graph = await compiled_graph()
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    return dict((snapshot.values or {}).get("computations") or {})


async def export_project(project: dict) -> None:
    """Rend et dépose le Word et le PDF de chaque document du projet.

    Une erreur est journalisée et n'emporte pas le processus : l'utilisateur
    relance l'export. Rien n'est enregistré pour un fichier qui n'a pas été
    déposé.
    """
    project_id = project["id"]
    documents = ["cdc", "bp"] if project["documents"] == "both" else [project["documents"]]
    catalogue = load_catalogue()
    try:
        async with connection() as conn:
            rows = await load_sections(conn, project_id)
        computations = await _computations(project["thread_id"])
        for document in documents:
            profil = project["profil_cdc"] if document == "cdc" else project["profil_bp"]
            exported = assemble(document, project["nom"], profil, rows, catalogue)
            charts = charts_for(computations) if document == "bp" else []
            word = render_word(exported, charts)
            pdf = await render_pdf(word, exported, charts)

            for format, data, content_type, faithful in (
                ("docx", word, _WORD, True),
                ("pdf", pdf.data, "application/pdf", pdf.faithful),
            ):
                path = f"{project_id}/{document}.{format}"
                await storage.upload(path, data, content_type)
                async with connection() as conn:
                    await record_export(conn, project_id, document=document,
                                        format=format, storage_path=path,
                                        draft=exported.draft, faithful=faithful)
    except Exception:
        logger.exception("export du projet %s en échec", project_id)


async def cancel_all() -> None:
    """Annule les exports en cours et attend qu'ils s'arrêtent. Même motif,
    et même raison, que `app.runs.registry.cancel_all`."""
    pending = dict(_exports)
    for task in pending.values():
        task.cancel()
    for project_id, task in pending.items():
        try:
            await task
        except BaseException:
            logger.debug("export %s arrêté", project_id, exc_info=True)
        if _exports.get(project_id) is task:
            del _exports[project_id]
