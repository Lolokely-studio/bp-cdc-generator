import asyncio

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
    # Se retirer soi-même à la fin : sans ce rappel, un projet dont le run
    # est terminé resterait marqué « en cours » et aucune reprise ne
    # repartirait jamais.
    task.add_done_callback(lambda _: _tasks.pop(project_id, None))


def is_running(project_id: str) -> bool:
    task = _tasks.get(project_id)
    return task is not None and not task.done()


async def cancel_all() -> None:
    """Annule tout et attend que ce soit fait. Appelée à l'arrêt de
    l'application, et par les tests qui ont lancé une tâche de fond — sans
    quoi une tâche survivrait à son test et écrirait dans une base que le
    test suivant croit à lui."""
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _tasks.clear()
