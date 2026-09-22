import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.checkpointer import close_checkpointer, purge_checkpoints
from app.core.db import connection, pool
from app.llm.transport import close_clients
from app.runs import registry

logger = logging.getLogger(__name__)


async def reconcile_orphan_runs() -> int:
    """Passe en `failed` les runs que plus aucune tâche ne pilote (§8).

    Au redémarrage, le registre des tâches est vide — il vivait en mémoire —
    alors que des lignes portent encore `running`. Sans cette réconciliation,
    l'utilisateur attend devant un écran qui ne bougera plus jamais, et
    `/resume` refuserait de partir en croyant qu'un run tourne déjà.

    Le test du registre n'est pas superflu pour autant : cette fonction est
    aussi appelable à chaud, et un run bien vivant ne doit pas être abattu.

    L'écriture est conditionnelle (`fail_if_still_running`) : rien ne
    synchronise la lecture de `running_projects` avec les runs vivants, donc
    un run peut atteindre `waiting` entre les deux. Écrire sans condition
    écraserait ce statut plus récent par un `failed` périmé.
    """
    from app.projects.repository import fail_if_still_running, running_projects

    reconciled = 0
    async with connection() as conn:
        for row in await running_projects(conn):
            if registry.is_running(str(row["id"])):
                continue
            if await fail_if_still_running(conn, row["id"]):
                reconciled += 1
    return reconciled


async def purge_finished_projects() -> int:
    """Purge les points de reprise des projets terminés (§9.3), en filet.

    La purge normale tourne à la fin d'un run (`runner.advance`, juste après
    l'écriture de `done`). Celle-ci est celle de secours : elle rattrape les
    projets que le processus a fini de piloter sans jamais avoir eu la main
    pour la lancer lui-même — exactement ce qui arrive quand le redémarrage
    survient entre les deux.
    """
    from app.projects.repository import finished_projects

    purged = 0
    async with connection() as conn:
        for row in await finished_projects(conn):
            await purge_checkpoints(row["thread_id"])
            purged += 1
    return purged


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ouvre le pool au démarrage, réconcilie les runs orphelins, purge en
    filet, le referme à l'arrêt.
    """
    connection_pool = pool()
    await connection_pool.open(wait=True)

    # Le démarrage ne doit JAMAIS dépendre de ces deux tâches de ménage.
    # Sur un hébergement qui vient de se réveiller, une seule erreur de
    # base — le cas le plus probable au réveil — empêchait l'application de
    # démarrer avant cette garde : pas de `/health`, et l'hébergeur peut la
    # relancer en boucle sans jamais réussir. Chacune s'entoure de son
    # propre `try/except` : l'échec de l'une ne doit pas empêcher l'autre.
    try:
        orphans = await reconcile_orphan_runs()
        if orphans:
            logger.warning("%d run(s) orphelin(s) repassés en échec", orphans)
    except Exception:
        logger.exception("échec de la réconciliation des runs orphelins au démarrage")

    try:
        # §9.3, la purge « en filet » : celle de fin de run a pu ne jamais
        # tourner, précisément parce que le processus est mort en chemin.
        await purge_finished_projects()
    except Exception:
        logger.exception("échec de la purge de filet au démarrage")

    try:
        yield
    finally:
        # L'ordre compte : on annule d'abord les runs, ensuite seulement on
        # ferme ce dont ils se servent. L'inverse laisserait une tâche
        # vivante écrire dans un point de reprise dont la connexion vient
        # d'être fermée, et l'erreur remonterait dans une tâche que
        # personne n'attend, donc nulle part.
        await registry.cancel_all()
        try:
            await close_checkpointer()
        finally:
            try:
                await close_clients()
            finally:
                await connection_pool.close()


def create_app() -> FastAPI:
    """Construit l'application. Une fonction et non un module-niveau :
    les tests en créent une par cas, sans état partagé."""
    app = FastAPI(title="Esquisse", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Sonde de réveil. L'hébergement gratuit s'endort après quinze
        minutes ; l'interface appelle cette route et affiche un écran
        d'attente le temps du redémarrage."""
        return {"statut": "ok"}

    from app.auth.routes import router as auth_router
    app.include_router(auth_router)

    from app.auth.routes import me_router
    app.include_router(me_router)

    from app.projects.routes import router as projects_router
    app.include_router(projects_router)

    return app


app = create_app()
