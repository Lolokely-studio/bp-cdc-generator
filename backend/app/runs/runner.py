import logging
from uuid import UUID

import asyncio

from app.agent import checkpointer
from app.agent.graph import compiled_graph
from app.core.db import connection
from app.projects.repository import set_run_status
from app.runs import registry
from app.runs.events import RunEvent, publish

logger = logging.getLogger(__name__)


class RunAlreadyRunning(RuntimeError):
    """Un run avance déjà pour ce projet.

    Ce n'est pas une erreur d'utilisateur mais un garde-fou : deux tâches sur
    le même `thread_id` écriraient deux points de reprise concurrents.
    """


def start_run(project_id: str, thread_id: str, graph_input) -> None:
    """Lance le run en tâche de fond et rend la main tout de suite.

    La requête HTTP qui appelle ceci ne doit pas attendre : une section prend
    des dizaines de secondes et le §8 veut que la coupure du client ne change
    rien au run.
    """
    if registry.is_running(project_id):
        raise RunAlreadyRunning(project_id)
    task = asyncio.create_task(advance(project_id, thread_id, graph_input))
    registry.register(project_id, task)


async def advance(project_id: str, thread_id: str, graph_input,
                  *, _force_done: bool = False) -> None:
    """Avance le graphe jusqu'à l'interruption suivante ou jusqu'au bout.

    Fonction séparée de `start_run` pour être appelable directement : un test
    du pilote n'a pas à se battre avec l'ordonnanceur pour savoir quand la
    tâche a fini.

    `_force_done` sert au test de la purge, qui a besoin d'atteindre le
    chemin de fin sans dérouler trente sections.
    """
    config = {"configurable": {"thread_id": thread_id}}
    await _status(project_id, "running")
    try:
        if not _force_done:
            graph = await compiled_graph()
            await graph.ainvoke(graph_input, config=config)
            snapshot = await graph.aget_state(config)
            if snapshot.interrupts:
                await _publish_interrupt(project_id, snapshot.interrupts[0])
                await _status(project_id, "waiting")
                return
    except asyncio.CancelledError:
        # L'arrêt de l'application. Le point de reprise a déjà tout ce qu'il
        # faut ; la réconciliation du démarrage suivant remettra le projet en
        # `failed` et proposera « Reprendre ».
        raise
    except Exception as error:
        # Une tâche dont personne n'attend le résultat avale son exception
        # jusqu'au ramasse-miettes : sans ce bloc, un run mourrait en silence
        # et `run_status` resterait à `running` pour toujours.
        logger.exception("run %s en échec", project_id)
        await _status(project_id, "failed")
        publish(project_id, RunEvent("error", {
            "code": "run_en_echec",
            "message": str(error) or error.__class__.__name__,
            "reprenable": True,
        }))
        return

    await _status(project_id, "done")
    # §9.3 : la purge tourne à la fin d'un run. L'appel passe par le module
    # et non par un nom importé, pour que le test puisse le remplacer.
    removed = await checkpointer.purge_checkpoints(thread_id)
    logger.info("run %s terminé, %d points de reprise purgés", project_id, removed)
    publish(project_id, RunEvent("done", {"project_id": project_id}))


async def _publish_interrupt(project_id: str, interrupt) -> None:
    """Publie l'interruption avec son identifiant.

    L'identifiant vient de LangGraph et non de nous : c'est lui que
    `POST /answer` renverra, et c'est en le comparant à l'interruption
    current qu'on saura si la requête rejoue un point déjà dépassé (§6.2).
    """
    publish(project_id, RunEvent("interaction", {
        "id": interrupt.id,
        **interrupt.value,
    }))


async def _status(project_id: str, statut: str) -> None:
    async with connection() as conn:
        await set_run_status(conn, UUID(project_id), statut)
