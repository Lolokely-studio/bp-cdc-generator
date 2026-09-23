import asyncio
import logging
from datetime import datetime, timezone
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
from app.projects.repository import exports_of_project, record_exports

logger = logging.getLogger(__name__)

_WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Un export en cours par projet. En mémoire du processus, comme le registre
# des runs, et pour la même raison (§9.2, une seule instance).
_exports: dict[str, asyncio.Task] = {}

# L'issue du dernier export par projet, en mémoire comme le registre (§9.2).
_outcomes: dict[str, str] = {}


def last_outcome(project_id: str) -> str | None:
    return _outcomes.get(project_id)


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


def _export_stamp() -> str:
    """Un horodatage tiré une seule fois par export, UTC, à la microseconde.

    `YYYYMMDDTHHMMSSffffffZ` : trié comme une chaîne, il se trie dans l'ordre
    chronologique — ce qui compte n'est pas le format mais que ce soit unique
    par export et lisible tel quel dans un chemin de stockage.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


async def export_project(project: dict) -> None:
    """Rend, dépose et enregistre les fichiers de chaque document du projet.

    Quatre temps, dans cet ordre, pour qu'un dépôt interrompu ne soit jamais
    visible : tout rendre, puis tout déposer SOUS UN NOUVEAU PRÉFIXE
    horodaté, puis tout enregistrer en une transaction, puis seulement
    ensuite supprimer l'ancien préfixe. Comme `GET /exports` ne sert que les
    chemins que la base nomme, un dépôt qui échoue en cours de route laisse
    les lignes — donc les liens et les drapeaux affichés — pointer sur
    l'export précédent, entier et déjà validé : l'écran ne montre jamais un
    mélange d'ancien et de nouveau. L'issue est gardée en mémoire et rendue
    par `GET` : un export raté se dit, il ne se devine pas.
    """
    project_id = project["id"]
    key = str(project_id)
    documents = ["cdc", "bp"] if project["documents"] == "both" else [project["documents"]]
    catalogue = load_catalogue()
    try:
        async with connection() as conn:
            rows = await load_sections(conn, project_id)
            # Lues AVANT le nouveau dépôt : ce sont les seuls chemins dont on
            # sache, une fois la transaction ci-dessous passée, qu'ils ne
            # sont plus référencés par aucune ligne.
            previous = await exports_of_project(conn, project_id)
        computations = await _computations(project["thread_id"])

        files = []
        for document in documents:
            profil = project["profil_cdc"] if document == "cdc" else project["profil_bp"]
            exported = assemble(document, project["nom"], profil, rows, catalogue)
            charts = charts_for(computations) if document == "bp" else []
            word = render_word(exported, charts)
            pdf = await render_pdf(word, exported, charts)
            files.append({"document": document, "format": "docx", "data": word,
                          "content_type": _WORD, "draft": exported.draft,
                          "faithful": True})
            files.append({"document": document, "format": "pdf", "data": pdf.data,
                          "content_type": "application/pdf",
                          "draft": exported.draft, "faithful": pdf.faithful})

        prefix = f"{project_id}/{_export_stamp()}"
        for f in files:
            f["storage_path"] = f"{prefix}/{f['document']}.{f['format']}"
            await storage.upload(f["storage_path"], f["data"], f["content_type"])

        async with connection() as conn:
            await record_exports(conn, project_id, files)
        _outcomes[key] = "ok"

        # Le ménage vient après coup, et ne doit jamais faire échouer un
        # export déjà enregistré : un fichier orphelin coûte quelques
        # centaines de kilo-octets, pas une erreur.
        #
        # Deux formes de chemin à distinguer, pas une seule coupe au dernier
        # `/`. Un chemin HORODATÉ (`{project_id}/{horodatage}/{document}.
        # {format}`, trois segments) se supprime par préfixe : son dossier
        # n'appartient qu'à lui. Un chemin PLAT hérité d'avant ce correctif
        # (`{project_id}/{document}.{format}`, deux segments) donnerait par
        # la même coupe `{project_id}` tout court — l'ANCÊTRE du dossier
        # horodaté qu'on vient d'écrire, pas un dossier à lui : le supprimer
        # supprimerait le nouvel export. On ne sait pas non plus lui faire
        # correspondre un objet exact (`storage.delete_prefix` liste un
        # dossier, il ne cible pas un fichier précis) : plutôt que de
        # deviner, ce chemin hérité est laissé orphelin — même coût qu'un
        # dépôt interrompu (§7 de la doc).
        old_prefixes = set()
        for row in previous:
            segments = row["storage_path"].split("/")
            if len(segments) >= 3:
                old_prefixes.add("/".join(segments[:-1]))
            else:
                logger.info(
                    "export du projet %s : chemin hérité %s laissé "
                    "orphelin (pas de suppression sûre par préfixe)",
                    project_id, row["storage_path"])
        old_prefixes.discard(prefix)
        for old_prefix in old_prefixes:
            try:
                await storage.delete_prefix(old_prefix)
            except Exception:
                logger.exception(
                    "suppression de l'ancien préfixe %s en échec (projet %s)",
                    old_prefix, project_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("export du projet %s en échec", project_id)
        _outcomes[key] = "echec"


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
