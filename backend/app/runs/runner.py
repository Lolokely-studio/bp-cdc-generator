import asyncio
import logging
from uuid import UUID

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


async def advance(project_id: str, thread_id: str, graph_input) -> None:
    """Avance le graphe jusqu'à l'interruption suivante ou jusqu'au bout.

    Fonction séparée de `start_run` pour être appelable directement : un test
    du pilote n'a pas à se battre avec l'ordonnanceur pour savoir quand la
    tâche a fini.
    """
    config = {"configurable": {"thread_id": thread_id}}
    await _status(project_id, "running")
    try:
        graph = await compiled_graph()
        await graph.ainvoke(graph_input, config=config)
        snapshot = await graph.aget_state(config)

        # Le statut AVANT la publication, dans les deux sorties. Un client
        # qui appelle `/state` en réaction à l'événement doit trouver la
        # colonne déjà à jour ; l'ordre inverse lui montrerait l'état
        # d'avant, une fois sur on ne sait combien.
        #
        # CES DEUX ÉCRITURES SONT DANS LE `try` : constat 2 de la revue
        # finale. Si `_status("waiting")` lève, la ligne restait `running`
        # pour toujours faute d'être rattrapée ; elle passe maintenant par
        # `_fail`, comme n'importe quel autre échec du run.
        if snapshot.interrupts:
            await _status(project_id, "waiting")
            await _publish_interrupt(project_id, snapshot.interrupts[0])
            return

        await _status(project_id, "done")
    except asyncio.CancelledError:
        # L'arrêt de l'application. On ne touche pas au statut : la ligne
        # reste `running` et la réconciliation du démarrage suivant la
        # repassera en `failed` en proposant « Reprendre » (tâche 7). Tant
        # que cette réconciliation n'existe pas, la colonne ment après une
        # annulation — c'est assumé, et c'est la tâche 7 qui le referme.
        #
        # Cette clause est documentaire : depuis Python 3.8,
        # `CancelledError` hérite de `BaseException` et non d'`Exception`,
        # donc le bloc suivant ne l'aurait pas attrapée de toute façon. On
        # l'écrit pour que le lecteur sache que le cas a été pesé, pas
        # oublié.
        raise
    except Exception as error:
        await _fail(project_id, error)
        return

    # §9.3 : la purge tourne à la fin d'un run. L'appel passe par le module
    # et non par un nom importé, pour que le test puisse le remplacer.
    #
    # HORS DU `try` CI-DESSUS, ET DANS SON PROPRE `try/except` : constat 2 de
    # la revue finale. Une purge ratée n'est qu'un coût de stockage — la
    # purge de filet du démarrage (§9.3, `purge_finished_projects`) la
    # rattrapera — mais elle ne doit jamais faire perdre l'événement `done`.
    # Le laisser lever depuis une tâche que personne n'attend faisait sortir
    # l'exception en silence : le client SSE ne recevait plus que des
    # battements, ne se reconnectait jamais, et l'écran restait sur
    # « rédaction en cours » alors que la ligne était bel et bien `done`.
    try:
        removed = await checkpointer.purge_checkpoints(thread_id)
        logger.info("run %s terminé, %d points de reprise purgés", project_id, removed)
    except Exception:
        logger.exception("run %s : purge des points de reprise en échec", project_id)
    publish(project_id, RunEvent("done", {"project_id": project_id}))


async def _fail(project_id: str, error: Exception) -> None:
    """Marque l'échec sans jamais le perdre.

    L'événement part AVANT l'écriture en base, et l'écriture est elle-même
    gardée. `_status` ouvre une connexion : si la base est la cause de
    l'échec initial — le cas le plus probable — elle lèvera ici aussi. Dans
    l'ordre inverse, cette seconde levée emporterait la publication et
    s'échapperait d'une tâche que personne n'attend : le run mourrait en
    silence et `run_status` resterait à `running` pour toujours, c'est-à-dire
    exactement ce que ce bloc existe pour empêcher. Constaté sur une sonde,
    pas déduit.

    `logger.exception` est appelé sous une exception active, il journalise
    donc la trace complète.
    """
    logger.exception("run %s en échec", project_id)
    publish(project_id, RunEvent("error", {
        "code": "run_en_echec",
        "message": str(error) or error.__class__.__name__,
        "reprenable": True,
    }))
    try:
        await _status(project_id, "failed")
    except Exception:
        logger.exception(
            "run %s : impossible d'écrire le statut d'échec", project_id)


async def _publish_interrupt(project_id: str, interrupt) -> None:
    """Publie l'interruption avec son identifiant.

    L'identifiant vient de LangGraph et non de nous : c'est lui que
    `POST /answer` renverra, et c'est en le comparant à l'interruption
    courante qu'on saura si la requête rejoue un point déjà dépassé (§6.2).
    """
    publish(project_id, RunEvent("interaction", {
        "id": interrupt.id,
        **interrupt.value,
    }))


async def _status(project_id: str, status: str) -> None:
    async with connection() as conn:
        await set_run_status(conn, UUID(project_id), status)
