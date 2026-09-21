from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.graph import compiled_graph, initial_state
from app.agent.projections import load_facts, load_sections
from app.agent.templates import load_catalogue
from app.auth.dependencies import active_user
from app.core.db import connection
from app.projects.repository import (
    ProjectNotFound,
    create_project,
    project_for_user,
    projects_of_user,
)
from app.projects.schemas import ProjectCreate, ProjectState, ProjectSummary
from app.runs.runner import RunAlreadyRunning, start_run

router = APIRouter(prefix="/projects", tags=["projets"])


async def _owned(project_id: UUID, user) -> dict:
    """Le projet, ou 404.

    `project_for_user` LÈVE `ProjectNotFound` — elle ne rend pas `None`.
    Sa docstring dit pourquoi les deux cas se confondent : « n'existe pas »
    et « appartient à quelqu'un d'autre » se répondent pareil, sans quoi les
    identifiants deviendraient énumérables. On traduit l'exception en 404,
    on ne réinvente pas le filtre.
    """
    async with connection() as conn:
        try:
            return await project_for_user(conn, project_id, user["id"])
        except ProjectNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                {"code": "projet_introuvable"}) from None


@router.post("", status_code=status.HTTP_201_CREATED,
             response_model=ProjectSummary)
async def create(body: ProjectCreate, user=Depends(active_user)):
    """Crée le projet et démarre son run.

    Le `thread_id` est tiré ici et porté par la ligne : c'est la seule chose
    qui relie une ligne `projects` à son point de reprise LangGraph, et la
    contrainte d'unicité de la colonne empêche deux projets de partager un
    fil.
    """
    thread_id = f"projet-{uuid4()}"
    catalogue = load_catalogue()
    async with connection() as conn:
        project_id = await create_project(
            conn, user["id"], nom=body.nom, documents=body.documents,
            profil_cdc=body.profil_cdc, profil_bp=body.profil_bp,
            thread_id=thread_id,
            templates_version=str(catalogue.cdc.version),
        )
    start_run(
        str(project_id), thread_id,
        initial_state(str(project_id), body.documents, body.profil_cdc,
                      body.profil_bp, body.idee),
    )
    # On ne guette pas un statut « stable » avant de répondre : le run vient
    # de partir en tâche de fond et la ligne peut porter encore `idle`.
    # Attendre ici rendrait la création lente et le code de retour
    # dépendant de l'ordonnanceur.
    async with connection() as conn:
        row = await project_for_user(conn, project_id, user["id"])
    return ProjectSummary(**row)


@router.get("", response_model=list[ProjectSummary])
async def listing(user=Depends(active_user)):
    async with connection() as conn:
        return [ProjectSummary(**row)
                for row in await projects_of_user(conn, user["id"])]


@router.get("/{project_id}", response_model=ProjectSummary)
async def header(project_id: UUID, user=Depends(active_user)):
    return ProjectSummary(**await _owned(project_id, user))


@router.get("/{project_id}/state", response_model=ProjectState)
async def state(project_id: UUID, user=Depends(active_user)):
    """L'état complet, lu du point de reprise pour l'interaction et des
    projections pour le reste.

    Deux sources et non une seule : le point de reprise sait seul quelle
    interruption est en attente, les projections répondent sans réhydrater
    le graphe — ce qui est tout leur objet (§4.6).
    """
    row = await _owned(project_id, user)
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)

    interaction = None
    if snapshot.interrupts:
        pending = snapshot.interrupts[0]
        interaction = {"id": pending.id, **pending.value}

    values = snapshot.values or {}
    async with connection() as conn:
        facts = await load_facts(conn, project_id)
        sections = await load_sections(conn, project_id)

    return ProjectState(
        projet=ProjectSummary(**row),
        plan=[ref.model_dump() for ref in values.get("plan", [])],
        curseur=values.get("cursor", 0),
        faits={key: fact.model_dump() for key, fact in facts.items()},
        sections=sections,
        interaction=interaction,
    )
