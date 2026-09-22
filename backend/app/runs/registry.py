import asyncio
import logging

logger = logging.getLogger(__name__)

# Une tâche par projet, sur la durée de vie du processus.
#
# COMME LE BUS, CE REGISTRE EST EN MÉMOIRE (§9.2). Avec deux instances,
# chacune croirait être seule à piloter un projet et deux runs avanceraient
# le même graphe en parallèle — deux points de reprise concurrents sur le
# même `thread_id`, c'est-à-dire de la corruption silencieuse. La contrainte
# « une seule instance » n'est pas un détail d'exploitation, elle est
# structurelle tant que ce dictionnaire existe.
_tasks: dict[str, asyncio.Task] = {}


def register(project_id: str, task: asyncio.Task) -> None:
    _tasks[project_id] = task
    # Le rappel de fin vérifie l'IDENTITÉ de la tâche avant de retirer
    # l'entrée, et ce n'est pas une précaution de style.
    #
    # `is_running` passe à faux dès qu'une tâche se termine, mais le rappel
    # ne s'exécute qu'au tour de boucle suivant. Dans cet intervalle, une
    # coroutine déjà prête — une requête `/answer` qui reprend, par exemple —
    # passe le garde, `register` remplace l'entrée, puis le rappel de la
    # tâche A efface l'entrée de la tâche B. Deux tâches avancent alors le
    # même `thread_id` — exactement la corruption que ce module existe pour
    # empêcher — et `cancel_all` ne voit plus l'orpheline.
    #
    # Reproduit, pas supposé : la relecture de cette tâche en a produit une
    # démonstration autonome.
    task.add_done_callback(_forget(project_id))


def _forget(project_id: str):
    """Le rappel qui ne retire que sa propre tâche."""
    def _callback(task: asyncio.Task) -> None:
        if _tasks.get(project_id) is task:
            del _tasks[project_id]
    return _callback


def is_running(project_id: str) -> bool:
    task = _tasks.get(project_id)
    return task is not None and not task.done()


async def cancel_all() -> None:
    """Annule tout et attend que ce soit fait.

    Appelée à l'arrêt de l'application, et par les tests qui ont lancé une
    tâche de fond — sans quoi une tâche survivrait à son test et écrirait
    dans une base que le test suivant croit à lui.
    """
    pending = dict(_tasks)
    for task in pending.values():
        task.cancel()
    for project_id, task in pending.items():
        try:
            await task
        except BaseException:
            # `BaseException` et non `Exception` : l'annulation qu'on vient
            # de demander se présente en `CancelledError`, qui n'hérite plus
            # d'`Exception` depuis Python 3.8. Un vrai échec de run remonte
            # aussi par ici à l'arrêt ; on le journalise plutôt que de le
            # perdre en silence.
            logger.debug("run %s terminé à l'arrêt", project_id, exc_info=True)
        # On ne retire que ce qu'on a annulé. Un `_tasks.clear()` final
        # emporterait une tâche enregistrée pendant qu'on attendait.
        if _tasks.get(project_id) is task:
            del _tasks[project_id]
