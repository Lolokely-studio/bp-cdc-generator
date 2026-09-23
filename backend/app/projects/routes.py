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
    set_run_status,
)
from app.projects.schemas import (
    AnswerRequest,
    ProjectCreate,
    ProjectState,
    ProjectSummary,
    ReopenRequest,
)
from app.projects.stream import event_stream
from app.runs import registry
from app.runs.runner import RunAlreadyRunning, start_run
from app.agent.nodes import rework_queue
from app.export.service import is_exporting

router = APIRouter(prefix="/projects", tags=["projets"])

# La forme que chaque interruption attend, telle que les nœuds la lisent.
# `ask_questions` veut une correspondance fait → valeur, `review` un
# dictionnaire d'action, `arbitrate` une liste d'arbitrages.
_EXPECTED_ANSWER = {"questions": dict, "review": dict, "inconsistencies": list}


def summary(row: dict) -> ProjectSummary:
    """L'en-tête d'un projet, avec la taille de son plan.

    La taille se recalcule depuis le catalogue plutôt que depuis le point de
    reprise : la liste des projets l'affiche pour chacun, et réhydrater un
    graphe par carte du tableau de bord coûterait une requête lourde chacune.
    `plan_for` est déterministe pour des documents et des profils donnés.
    """
    try:
        total = len(load_catalogue().plan_for(
            row["documents"], row["profil_cdc"], row["profil_bp"]))
    except ValueError:
        total = 0
    return ProjectSummary(**row, sections_total=total)


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
            idee=body.idee,
        )
    graph_input["project_id"] = str(project_id)
    start_run(str(project_id), thread_id, graph_input)
    # On ne guette pas un statut « stable » avant de répondre : le run vient
    # de partir en tâche de fond et la ligne peut porter encore `idle`.
    # Attendre ici rendrait la création lente et le code de retour
    # dépendant de l'ordonnanceur.
    async with connection() as conn:
        row = await project_for_user(conn, project_id, user["id"])
    return summary(row)


@router.get("", response_model=list[ProjectSummary])
async def listing(user=Depends(active_user)):
    async with connection() as conn:
        return [summary(row)
                for row in await projects_of_user(conn, user["id"])]


@router.get("/{project_id}", response_model=ProjectSummary)
async def header(project_id: UUID, user=Depends(active_user)):
    return summary(await _owned(project_id, user))


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
    # dernier. `waiting` avec `interaction: null` EXISTE VRAIMENT, et pas
    # seulement en théorie : reproduit en élargissant la fenêtre pendant
    # laquelle `/answer` tourne — la ligne dit encore `waiting` alors que le
    # point de reprise a déjà consommé la réponse et n'expose plus rien tant
    # que le nœud suivant n'a pas écrit sa propre interruption. C'est un état
    # DE PASSAGE, jamais définitif : le front qui le rencontre doit relire
    # `/state`, pas l'interpréter comme une incohérence à corriger ici.
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
        projet=summary(row),
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
    # DEUX LECTURES, ET RIEN NE LES SYNCHRONISE — contrairement à `/state`,
    # cette route ne lit aucune projection : la ligne, pour `run_status`
    # dans les réponses ci-dessous, puis le point de reprise, pour
    # l'interruption en attente. `waiting` avec une interruption déjà
    # consommée EXISTE VRAIMENT : c'est la fenêtre de CETTE requête elle-même
    # — la ligne dit encore `waiting` pendant qu'un `/answer` concurrent (ou
    # ce traitement-ci, une fois arrivé au `start_run` plus bas) a déjà fait
    # avancer le point de reprise. Un état de passage, pas une incohérence.
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

    N'AGIT QUE SUR `failed`, `running` ORPHELIN (plus aucune tâche vivante),
    OU `idle` SANS AUCUN POINT DE REPRISE. Sur `waiting`, ce n'est pas un
    crash mais une vraie interruption en attente : relancer rejouerait le
    nœud interrompu et ferait refuser par le 409 de `/answer` la réponse que
    l'utilisateur est peut-être en train d'envoyer. Sur `done`, il n'y a plus
    rien à faire.

    UN PROJET MORT-NÉ n'a jamais écrit le moindre point de reprise, donc
    `snapshot.values` est vide : soit le premier `advance` a levé avant d'y
    parvenir (un délai d'attente du pool, par exemple, et la ligne est
    `failed`), soit le processus a été tué entre l'insertion de la ligne et
    le démarrage de la tâche (et la ligne est restée `idle`). Repasser
    `None` à LangGraph dans ce cas fait lever « Received no input for
    __start__ » : la ligne retombe en `failed`, présentée comme reprenable,
    et la même tentative se répète indéfiniment. On reconstruit alors
    `initial_state` depuis la ligne plutôt que de reprendre un point de
    reprise qui n'existe pas — c'est pour cela que `/resume` accepte `idle`
    exactement ici, et nulle part ailleurs : un `idle` qui a DÉJÀ un point de
    reprise n'est pas mort-né, il attend son premier tour de boucle. Sur une
    ligne ancienne dont `idee` est nulle (écrite avant la migration 0004), on
    refuse plutôt que de relancer sur une idée vide.
    """
    row = await _owned(project_id, user)
    if registry.is_running(str(project_id)):
        return {"reprise": False, "run_status": "running"}

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": row["thread_id"]}}
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}

    if not values:
        if row["run_status"] not in ("idle", "failed", "running"):
            return {"reprise": False, "run_status": row["run_status"]}
        if not row["idee"]:
            return {"reprise": False, "run_status": row["run_status"]}
        graph_input = initial_state(str(project_id), row["documents"],
                                    row["profil_cdc"], row["profil_bp"],
                                    row["idee"])
        try:
            start_run(str(project_id), row["thread_id"], graph_input)
        except RunAlreadyRunning:
            # Constat 3 de la revue finale, voir plus bas : rien n'est perdu,
            # une reprise ne porte aucune charge utile.
            return {"reprise": False, "run_status": "running"}
        return {"reprise": True, "run_status": "running"}

    if row["run_status"] not in ("failed", "running"):
        # Ici, `running` ne peut désigner qu'un run ORPHELIN : le garde
        # ci-dessus a déjà écarté celui que le registre pilote encore.
        return {"reprise": False, "run_status": row["run_status"]}

    # `save_facts` et non `reproject` : le point de reprise porte les faits,
    # jamais les sections déjà validées. Voir la note ci-dessous — ce n'est
    # pas un raccourci, c'est la seule projection qu'il puisse reconstruire.
    async with connection() as conn:
        await save_facts(conn, project_id, values.get("facts", {}))

    # `None` et non un état neuf : LangGraph repart du point de reprise. Lui
    # passer un état reconstruit écraserait ce qu'il a gardé.
    try:
        start_run(str(project_id), row["thread_id"], None)
    except RunAlreadyRunning:
        # Un double clic sur « Reprendre » : les deux requêtes passent le
        # garde `is_running` ci-dessus avant que l'une ou l'autre n'ait pu
        # s'enregistrer, attendent toutes deux `aget_state` et `save_facts`,
        # puis se disputent `start_run`. La seconde lève ici plutôt que de
        # rendre un 500 — et c'est sans perte : une reprise ne porte aucune
        # charge utile, contrairement à `/answer`.
        return {"reprise": False, "run_status": "running"}
    return {"reprise": True, "run_status": "running"}


# Ce que reçoit une section rouverte parce qu'une autre, dont elle dépend, va
# changer : sans cette raison, le rédacteur n'a rien à corriger et recopie.
REOPEN_DEPENDENT_NOTE = (
    "la section {target}, dont celle-ci dépend, vient d'être réécrite : "
    "aligne celle-ci sur son nouveau contenu"
)


@router.post("/{project_id}/sections/{section_id}/reopen")
async def reopen(project_id: UUID, section_id: str,
                 body: ReopenRequest | None = None,
                 user=Depends(active_user)):
    """Rouvre une section et celles qui en dépendent, puis les fait réécrire.

    Rouvrir la seule section demandée laisserait le document incohérent :
    celles qui la citent dans leur `depend_de` ont été écrites en s'appuyant
    sur ce qu'elle disait.

    SEULEMENT SUR UN PROJET `done`. Pendant un run, la file de réécriture
    concurrencerait le point de reprise ; en `failed`, c'est `/resume` qu'il
    faut d'abord. Et jamais pendant un export, qui lirait des sections à
    moitié réécrites et les mélangerait aux autres. Un refus ne marque rien.
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
        # choisir un au hasard.
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            {"code": "section_ambigue"})

    if row["run_status"] != "done" or registry.is_running(str(project_id)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "reouverture_impossible"})
    if is_exporting(str(project_id)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "export_deja_en_cours"})

    target = f"{matching[0].document}.{section_id}"
    queue = rework_queue(plan, load_catalogue().sections_depending_on(target))
    notes = {q: [REOPEN_DEPENDENT_NOTE.format(target=target)]
             for q in queue if q != target}
    if body is not None and body.consigne and body.consigne.strip():
        notes[target] = [body.consigne.strip()]

    async with connection() as conn:
        touched = await mark_for_reopening(conn, project_id, set(queue))
        # CONSTAT 4 DE LA REVUE FINALE : sans cette écriture, la ligne garde
        # `done` jusqu'à ce que la tâche de fond (`app.runs.runner.advance`)
        # écrive `running` à son premier `await` — une fenêtre bien réelle,
        # pas seulement théorique. Un `GET /projects/{id}` lu par le front
        # dans cette fenêtre revoit `done`, se rabat sur l'écran de fin, et
        # cet écran n'ouvre aucun flux et ne se rafraîchit jamais : rien ne
        # le fait jamais sortir de là. `advance` réécrira `running` juste
        # après, sans dommage — la même valeur, une seconde fois.
        await set_run_status(conn, project_id, "running")
    try:
        start_run(str(project_id), row["thread_id"],
                  {"rework": queue, "rework_notes": notes})
    except RunAlreadyRunning:
        # Deux clics sur « Rouvrir » : le second trouve le premier déjà
        # parti. Les lignes sont marquées, le premier run les réécrit. Ce
        # n'est pas la même situation que `reouverture_impossible` ci-dessus
        # (projet pas terminé) : ici la réécriture a bel et bien démarré, et
        # le dire faussement empêcherait l'utilisateur de simplement aller la
        # suivre sur l'écran de rédaction.
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "reecriture_deja_lancee"}) from None
    return {"sections": queue, "touchees": touched, "run_status": "running"}
