import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent import nodes
from app.agent.checkpointer import saver
from app.agent.state import EsquisseState, Fact, Inconsistency
from app.agent.templates import load_catalogue

logger = logging.getLogger(__name__)


# Ce que porte `problems` quand l'utilisateur demande une réécriture sans
# dire ce qui ne va pas. Le rédacteur le reçoit tel quel : mieux vaut lui
# dire « on ne sait pas ce qui cloche, reprends autrement » que de lui
# tendre une liste vide, qui se lirait comme « rien à corriger ».
UNSPECIFIED_REWRITE = (
    "l'utilisateur a demandé une réécriture sans préciser ce qui ne va pas : "
    "reprends la section sous un autre angle"
)


async def ask_questions(state) -> dict:
    """Première des trois interruptions.

    `formuler_questions` et `poser_questions` sont deux nœuds séparés, comme
    le §4.3 l'impose : à la reprise, LangGraph rejoue le nœud interrompu et
    lui seul, donc l'appel au modèle qui a formulé les questions n'est jamais
    refacturé.

    Le brief plaçait le lot proposé sous `state["computations"]["_pending_questions"]`,
    mais l'état déclaré par la tâche 6 (voir `EsquisseState.pending_questions`
    dans `app/agent/state.py`) porte une clé dédiée : c'est elle qui doit être
    lue ici, et surtout vidée en retour — sans quoi le lot de questions
    resterait dans l'état, et donc dans chaque point de reprise, pour le reste
    du run.
    """
    proposed = state.get("pending_questions")
    questions = [q.model_dump() for q in proposed.questions] if proposed else []
    answers = interrupt({"kind": "questions", "questions": questions})
    # `answers` vient du client par `Command(resume=…)` et n'est validé par
    # personne avant d'arriver ici. Une liste, une chaîne ou un nombre y
    # produisaient une `AttributeError` qui tuait le run — et, LangGraph
    # rejouant la valeur stockée au point de reprise, une reprise correcte
    # replantait à l'identique. Le projet restait coincé pour de bon.
    #
    # `review` porte déjà ce garde (`isinstance(feedback, dict)`) ; il
    # manquait ici. On ignore ce qu'on ne sait pas lire plutôt que de mourir
    # dessus : la section reposera ses questions au tour suivant. C'est
    # aussi ce qui désempoisonne un point de reprise déjà corrompu.
    if not isinstance(answers, dict):
        if answers is not None:
            logger.warning("réponse ignorée, forme inattendue : %s",
                           type(answers).__name__)
        answers = {}
    # Les réponses sont filtrées contre le catalogue, exactement comme
    # `extract_facts` filtre ce que le modèle propose. C'était la seule des
    # deux portes d'entrée des faits à n'avoir aucun loquet, et l'écart
    # coûtait cher : une paire clé/valeur arbitraire devenait un
    # `Fact(source="user")`, donc protégé par `merge_facts` contre toute
    # correction ultérieure, puis persisté, puis compté parmi les « nombres
    # connus » du vérificateur — si bien qu'un chiffre inventé cessait d'être
    # signalé comme orphelin. C'est le garde-fou qui nous permet de nous
    # passer de recherche web ; il ne peut pas dépendre de la bonne foi du
    # client.
    known = load_catalogue().facts
    facts = {
        fact_id: Fact(fact_id=fact_id, value=value, source="user")
        for fact_id, value in answers.items()
        if fact_id in known
    }
    return {"facts": facts, "pending_questions": None}


async def review(state) -> dict:
    """Relecture d'une section. L'utilisateur valide, ou renvoie des demandes."""
    ref = state["plan"][state["cursor"]]
    feedback = interrupt({
        "kind": "review",
        "section": f"{ref.document}.{ref.section_id}",
        "score": state["score"],
        "problems": state["problems"],
        # Le brouillon lui-même. Sans lui, un navigateur rechargé pendant une
        # relecture n'aurait rien à montrer : le texte n'est pas encore en
        # projection (c'est `save` qui l'y écrit, après), et le flux qui l'a
        # porté est passé.
        "blocks": [block.model_dump(mode="json") if hasattr(block, "model_dump")
                   else block for block in state["draft"] or []],
    })
    if isinstance(feedback, dict) and feedback.get("action") == "skip":
        # « Passer la section » : gardée telle quelle, mais enregistrée
        # `skipped`, et l'export portera le filigrane Brouillon (§7).
        return {"problems": [], "skip_current": True}
    if isinstance(feedback, dict) and feedback.get("action") == "rewrite":
        # Une demande de réécriture sans motif reste une demande de
        # réécriture. `_route_after_review` route sur `problems` : rendre une
        # liste vide ici enverrait la section vers `save`, donc la marquerait
        # terminée, au moment précis où l'utilisateur vient de dire qu'elle ne
        # l'est pas. Un champ libre laissé vide suffisait à produire ça.
        problems = feedback.get("problems") or [UNSPECIFIED_REWRITE]
        return {"problems": problems, "revisions": 0}
    # Acceptation : le brief rendait `{}` ici, qui ne touche pas `problems`.
    # `_route_after_review` route sur `state["problems"]` pour décider entre
    # "write" et "save" ; comme la critique simulée ne rend jamais une liste
    # vide, un `{}` laissait `problems` non vidée après une acceptation et le
    # graphe repartait en écriture indéfiniment — une vraie boucle infinie,
    # observée hors ligne. Vider `problems` ici est ce que « l'utilisateur
    # valide » doit signifier : plus rien à corriger.
    return {"problems": []}


async def arbitrate(state) -> dict:
    """Arbitrage des incohérences relevées par le contrôle final.

    La réponse est une liste de décisions, une par incohérence :
    `{"index": 0, "decision": "corriger", "consigne": "…"}` ou
    `{"index": 1, "decision": "ignorer"}`. Une correction met en file les
    sections que l'incohérence nomme, avec la consigne pour problème à
    corriger ; le run les reprend avant de s'arrêter. Tout ce qui n'a pas
    cette forme est ignoré plutôt que de tuer le run : LangGraph rejouerait
    la même valeur à la reprise, et le projet resterait coincé.
    """
    if not state["inconsistencies"]:
        return {}
    rulings = interrupt({"kind": "inconsistencies",
                         "inconsistencies": state["inconsistencies"]})
    found = [Inconsistency.model_validate(item) if isinstance(item, dict) else item
             for item in state["inconsistencies"]]
    notes: dict[str, list[str]] = {}
    for ruling in rulings if isinstance(rulings, list) else []:
        if not isinstance(ruling, dict) or ruling.get("decision") != "corriger":
            continue
        index = ruling.get("index")
        # `bool` est un `int` en Python : `True` passerait pour l'index 1.
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if not 0 <= index < len(found):
            continue
        inconsistency = found[index]
        consigne = ruling.get("consigne")
        consigne = consigne.strip() if isinstance(consigne, str) else ""
        consigne = consigne or inconsistency.proposal or "corrige cette incohérence"
        note = (f"incohérence relevée : {inconsistency.description} "
                f"— arbitrage : {consigne}")
        for section in inconsistency.sections:
            notes.setdefault(section, []).append(note)
    queue = nodes.rework_queue(state["plan"], notes)
    return {"rework": queue, "rework_notes": {q: notes[q] for q in queue}}


def _route_after_review(state) -> str:
    return "write" if state["problems"] else "save"


def _route_from_start(state) -> str:
    """Un run neuf commence par l'extraction des faits. Une réécriture
    demandée sur un fil terminé — par `/reopen` — va droit à sa file : les
    faits sont déjà là, et les réextraire écraserait des déductions que
    l'utilisateur a pu corriger depuis."""
    return "next_rework" if state.get("rework") else "extract_facts"


def _route_after_arbitrate(state) -> str:
    return "next_rework" if state.get("rework") else END


def _route_after_next_rework(state) -> str:
    return "analyse_gaps" if state.get("reworking") else END


def build_graph() -> StateGraph:
    """Le graphe du §4.4, arête pour arête."""
    builder = StateGraph(EsquisseState)
    for name, function in (
        ("extract_facts", nodes.extract_facts),
        ("analyse_gaps", nodes.analyse_gaps),
        ("formulate_questions", nodes.formulate_questions),
        ("ask_questions", ask_questions),
        ("compute", nodes.compute),
        ("write", nodes.write),
        ("check_numbers", nodes.check_numbers),
        ("critique", nodes.critique),
        ("review", review),
        ("save", nodes.save),
        ("coherence_check", nodes.coherence_check),
        ("arbitrate", arbitrate),
        ("next_rework", nodes.next_rework),
    ):
        builder.add_node(name, function)

    builder.add_conditional_edges(START, _route_from_start,
                                  ["next_rework", "extract_facts"])
    builder.add_edge("extract_facts", "analyse_gaps")
    builder.add_conditional_edges(
        "analyse_gaps", nodes.route_after_gaps,
        ["formulate_questions", "compute", "write"],
    )
    builder.add_edge("formulate_questions", "ask_questions")
    builder.add_edge("ask_questions", "analyse_gaps")
    builder.add_edge("compute", "write")
    builder.add_edge("write", "check_numbers")
    builder.add_conditional_edges("check_numbers", nodes.route_after_numbers,
                                  ["write", "critique"])
    builder.add_conditional_edges("critique", nodes.route_after_critique,
                                  ["write", "review", "save"])
    builder.add_conditional_edges("review", _route_after_review, ["write", "save"])
    builder.add_conditional_edges("save", nodes.route_after_save,
                                  ["analyse_gaps", "coherence_check", "next_rework"])
    builder.add_edge("coherence_check", "arbitrate")
    builder.add_conditional_edges("arbitrate", _route_after_arbitrate,
                                  ["next_rework", END])
    builder.add_conditional_edges("next_rework", _route_after_next_rework,
                                  ["analyse_gaps", END])
    return builder


async def compiled_graph():
    return build_graph().compile(checkpointer=await saver())


def initial_state(project_id: str, documents: str, profil_cdc, profil_bp, idea: str):
    """L'état de départ. Les documents, les profils et l'idée sont déjà connus :
    l'API les a recueillis avant de démarrer le run, et la ligne `projects` ne
    peut pas exister sans eux."""
    return {
        "project_id": project_id,
        "documents": documents,
        "profil_cdc": profil_cdc,
        "profil_bp": profil_bp,
        "idea": idea,
        "facts": {},
        "plan": load_catalogue().plan_for(documents, profil_cdc, profil_bp),
        "cursor": 0,
        "draft": None,
        "score": None,
        "problems": [],
        "revisions": 0,
        "question_rounds": 0,
        "computations": {},
        "pending_questions": None,
        "inconsistencies": [],
        "rework": [],
        "rework_notes": {},
        "reworking": False,
        "skip_current": False,
    }
