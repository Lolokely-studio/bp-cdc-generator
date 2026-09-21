from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from app.agent.graph import compiled_graph, initial_state
from app.agent.projections import load_facts, load_sections, mark_for_reopening, save_facts
from app.agent.templates import load_catalogue
from app.auth.dependencies import active_user
from app.core.db import connection
from app.projects.repository import (
    ProjectNotFound,
    create_project,
    project_for_user,
    projects_of_user,
)
from app.projects.schemas import (
    AnswerRequest,
    ProjectCreate,
    ProjectState,
    ProjectSummary,
)
from app.projects.stream import event_stream
from app.runs import registry
from app.runs.runner import RunAlreadyRunning, start_run

router = APIRouter(prefix="/projects", tags=["projets"])

# La forme que chaque interruption attend, telle que les nœuds la lisent.
# `ask_questions` veut une correspondance fait → valeur, `review` un
# dictionnaire d'action, `arbitrate` une liste d'arbitrages.
_EXPECTED_ANSWER = {"questions": dict, "review": dict, "inconsistencies": list}


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
    # L'état de départ est construit AVANT l'insertion, et ce n'est pas un
    # détail d'ordre. `initial_state` appelle `plan_for`, qui LÈVE sur un
    # profil absent de `profils_disponibles`. Construit après, il laisserait
    # une ligne `projects` derrière lui que personne ne pourra jamais faire
    # avancer : l'appelant reçoit un 500 sans identifiant, et aucune route de
    # ce plan ne sait reprendre un projet dont on ignore l'existence.
    #
    # Le cas ne peut pas se produire aujourd'hui — les `Literal` des schémas
    # et les `profils_disponibles` des YAML coïncident — mais ce sont deux
    # listes tenues dans deux fichiers que rien ne relie. Vérifié : en
    # faisant lever `start_run`, la ligne survit bel et bien.
    graph_input = initial_state("", body.documents, body.profil_cdc,
                                body.profil_bp, body.idee)
    async with connection() as conn:
        project_id = await create_project(
            conn, user["id"], nom=body.nom, documents=body.documents,
            profil_cdc=body.profil_cdc, profil_bp=body.profil_bp,
            thread_id=thread_id,
            templates_version=str(catalogue.cdc.version),
        )
    graph_input["project_id"] = str(project_id)
    start_run(str(project_id), thread_id, graph_input)
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
    # L'ORDRE DES TROIS LECTURES EST PORTEUR, et rien ne les synchronise.
    # La ligne d'abord, le point de reprise ensuite, les projections en
    # dernier : le statut lu est donc le plus ancien des trois. Tant que les
    # statuts n'avancent que dans un sens, l'écart penche du bon côté — on
    # peut voir `running` à côté d'une interaction déjà présente, et le front
    # affiche une question sous une bannière « en cours » périmée d'un
    # sondage. Inverser les deux premières lectures donnerait `waiting` avec
    # `interaction: null` : un état qui n'a jamais existé, et qu'un front
    # rend en « répondez à la question qui n'est pas là ».
    #
    # La tâche 7 fait reculer les statuts (`failed` puis `running` à la
    # reprise) : c'est là qu'il faudra reposer la question.
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


@router.post("/{project_id}/answer")
async def answer(project_id: UUID, body: AnswerRequest,
                 user=Depends(active_user)):
    """Répond à l'interaction courante et relance le run (§6.2).

    L'idempotence se joue ici, pas dans le graphe : on compare l'identifiant
    reçu à celui de l'interruption en attente et on ne reprend que s'ils
    coïncident. Un double-clic, une reconnexion, un onglet resté ouvert sur
    un état dépassé — tous répondent 200 avec `rejoue: false`, et rien ne
    bouge.

    Cette lecture de l'idempotence tenait sur une prémisse que la tâche 7
    invalide : elle supposait qu'une seconde requête arrivant sur un run déjà
    lancé rejouait forcément LA MÊME réponse — vraie tant que la seule façon
    de relancer un run était un second `/answer` sur la même interruption,
    puisque le point de reprise cesse d'exposer cette interruption dès que la
    reprise démarre, et qu'une requête tardive tombe alors sur la branche
    « périmée » ci-dessus plutôt que sur le registre. `/resume` change la
    donne : un run planté laisse son interruption EN ATTENTE, donc `/resume`
    et un `/answer` tardif peuvent tous deux reconnaître le même identifiant
    courant et se disputer le registre. Si c'est `/resume` qui gagne la
    course, il relance sans consommer aucune réponse (`Command` vaut `None`),
    et un `/answer` perdant qui recevrait quand même `rejoue: false` ferait
    croire à l'utilisateur que sa réponse est passée alors qu'elle vient
    d'être jetée en silence.
    """
    # L'ORDRE DES TROIS LECTURES EST PORTEUR, et rien ne les synchronise.
    # La ligne d'abord, le point de reprise ensuite, les projections en
    # dernier : le statut lu est donc le plus ancien des trois. Tant que les
    # statuts n'avancent que dans un sens, l'écart penche du bon côté — on
    # peut voir `running` à côté d'une interaction déjà présente, et le front
    # affiche une question sous une bannière « en cours » périmée d'un
    # sondage. Inverser les deux premières lectures donnerait `waiting` avec
    # `interaction: null` : un état qui n'a jamais existé, et qu'un front
    # rend en « répondez à la question qui n'est pas là ».
    #
    # La tâche 7 fait reculer les statuts (`failed` puis `running` à la
    # reprise) : c'est là qu'il faudra reposer la question.
    row = await _owned(project_id, user)
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)

    pending = snapshot.interrupts[0] if snapshot.interrupts else None
    if pending is None or pending.id != body.interaction_id:
        return {"rejoue": False, "run_status": row["run_status"]}

    expected = _EXPECTED_ANSWER.get(pending.value.get("kind"))
    if (expected is not None and body.reponse is not None
            and not isinstance(body.reponse, expected)):
        # Refuser ici plutôt que de laisser le nœud s'en étrangler. Rien n'a
        # été consommé : l'interruption reste en attente et le client peut
        # renvoyer. `Any` sur le schéma reste le bon choix — les cinq
        # interruptions portent des charges utiles différentes — mais « le
        # graphe valide ce qu'il reçoit » n'était vrai que de `review`.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"code": "reponse_mal_formee"})

    try:
        start_run(str(project_id), row["thread_id"],
                  Command(resume={body.interaction_id: body.reponse}))
    except RunAlreadyRunning:
        # Un run avance déjà sur ce fil — mais on ne peut plus dire lequel
        # des deux appelants a gagné : un second `/answer` sur la même
        # interruption (la réponse gagnante est alors identique, rien n'est
        # perdu) ou un `/resume` sur un run planté (qui ne consomme aucune
        # réponse : LA réponse de CETTE requête serait jetée sans jamais
        # avoir été prise en compte). Rendre `rejoue: false` ici mentirait
        # dans ce second cas — l'utilisateur croirait avoir répondu.
        #
        # On choisit donc de rompre, sur cette seule branche, la promesse
        # « toujours 200 » du §6.2 : un 409 ne ment jamais, quand un
        # `rejoue: false` optimiste le ferait une fois sur deux. Le coût est
        # un aller-retour de plus pour le client, qui peut relire `/state`
        # et renvoyer sa réponse si l'interruption est toujours la sienne.
        # L'alternative — faire attendre la requête jusqu'à ce que la
        # reprise en cours atteigne sa prochaine interruption — tiendrait la
        # promesse, mais transformerait `/answer` en appel de durée
        # indéterminée, bornée par le temps d'une section entière : un coût
        # de latence sans budget clair, pour un cas que le client peut de
        # toute façon résoudre par une nouvelle lecture d'état.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "run_deja_en_cours"})
    return {"rejoue": True, "run_status": "running"}


@router.get("/{project_id}/stream")
async def stream(project_id: UUID, user=Depends(active_user)):
    """Le flux du §6.1.

    Le contrôle du propriétaire passe AVANT d'ouvrir le flux : une fois la
    réponse en cours, on ne peut plus changer son code de statut, et un 404
    tardif ne serait pas lisible par le client.

    `X-Accel-Buffering: no` et `Cache-Control: no-cache` disent aux
    intermédiaires de ne pas accumuler : sans eux, un proxy peut retenir le
    flux jusqu'à remplir un tampon, et l'utilisateur verrait la section
    apparaître d'un bloc à la fin — soit exactement ce que le flux existe
    pour éviter.
    """
    await _owned(project_id, user)
    return StreamingResponse(
        event_stream(str(project_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{project_id}/resume")
async def resume(project_id: UUID, user=Depends(active_user)):
    """Relance un run interrompu, depuis son point de reprise (§8).

    Les faits sont réécrits AVANT la relance, dans l'esprit du §4.6 : en cas
    de divergence, c'est le point de reprise qui gagne. Les sections, elles,
    ne s'y trouvent pas — il ne porte que la section en cours — et elles se
    réparent d'elles-mêmes, `save` écrivant la projection avant d'avancer le
    curseur. Un run mort entre les deux refait simplement sa section.
    """
    row = await _owned(project_id, user)
    if registry.is_running(str(project_id)):
        return {"reprise": False, "run_status": "running"}

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}

    # `save_facts` et non `reproject` : le point de reprise porte les faits,
    # jamais les sections déjà validées. Voir la note ci-dessous — ce n'est
    # pas un raccourci, c'est la seule projection qu'il puisse reconstruire.
    async with connection() as conn:
        await save_facts(conn, project_id, values.get("facts", {}))

    # `None` et non un état neuf : LangGraph repart du point de reprise. Lui
    # passer un état reconstruit écraserait ce qu'il a gardé.
    start_run(str(project_id), row["thread_id"], None)
    return {"reprise": True, "run_status": "running"}


@router.post("/{project_id}/sections/{section_id}/reopen")
async def reopen(project_id: UUID, section_id: str,
                 user=Depends(active_user)):
    """Rouvre une section et celles qui en dépendent.

    Rouvrir la seule section demandée laisserait le document incohérent :
    celles qui la citent dans leur `depend_de` ont été écrites en s'appuyant
    sur ce qu'elle disait.
    """
    row = await _owned(project_id, user)
    graph = await compiled_graph()
    snapshot = await graph.aget_state(
        {"configurable": {"thread_id": row["thread_id"]}})
    plan = (snapshot.values or {}).get("plan", [])

    matching = [ref for ref in plan if ref.section_id == section_id]
    if not matching:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            {"code": "section_introuvable"})
    if len(matching) > 1:
        # Possible depuis la migration 0003 : les deux documents peuvent
        # porter le même identifiant de section. On refuse plutôt que d'en
        # choisir un au hasard — le front, lui, sait de quel document il
        # parle, et pourra le préciser le jour où le cas se présente.
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            {"code": "section_ambigue"})

    qualified = load_catalogue().sections_depending_on(
        f"{matching[0].document}.{section_id}")
    async with connection() as conn:
        touched = await mark_for_reopening(conn, project_id, qualified)
    return {"sections": sorted(qualified), "touchees": touched}
