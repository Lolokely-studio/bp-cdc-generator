from typing import Any

from app.agent import prompts
from app.agent.assumptions import build_assumptions
from app.agent.finance import Computation, run_computation
from app.agent.numbers import orphan_numbers
from app.agent.projections import save_facts, save_section
from app.agent.state import Fact, SectionRef
from app.agent.templates import Catalogue, SectionTemplate, load_catalogue
from app.core.db import connection
from app.llm.gateway import complete, stream
from app.llm.types import StreamDone, StreamRestart, TextDelta

# Les deux plafonds du §4.4. Ils bornent des boucles qui, sans eux,
# tourneraient sur un projet mal renseigné ou un modèle qui s'entête.
MAX_QUESTION_ROUNDS = 2
MAX_REVISIONS = 2

# Sous ce seuil la machine réécrit ; le seuil de relecture, lui, vient des
# templates. Les deux font deux choses différentes et ne se confondent pas.
REWRITE_SCORE = 7

# Taille du lot de questions d'une section. Les faits requis le remplissent
# d'abord, les faits utiles prennent les places qui restent — c'est la règle
# que l'en-tête du catalogue décrit et qui n'avait jamais été écrite.
#
# Six : mesuré sur le plan complet du business plan, ce chiffre récupère les
# sept faits utiles dont les calculs financiers ont besoin, en quarante-sept
# questions formant un lot dans onze des quinze sections. Assez pour servir,
# trop peu pour ressembler à un interrogatoire.
#
# C'est un plancher avec du mou, pas un optimum : quatre récupère déjà les
# sept faits, trois en perd deux (`tresorerie_securite`, `taille_marche_sam`).
# Monter ne coûte rien, descendre sous quatre coûte des tableaux.
#
# Et la constante n'est pas seule porteuse : **l'ordre des `faits_utiles`
# dans chaque section YAML l'est autant**. `besoin_financement` n'atteint
# `aides_subventions` et `tresorerie_securite`, en quatrième et cinquième
# position, que parce que `emprunt_montant` et `emprunt_duree` ont déjà été
# répondus dans une section antérieure et sortent du lot. Réordonner une
# liste de faits utiles peut donc coûter un tableau, en silence.
QUESTION_BATCH_SIZE = 6


def _catalogue() -> Catalogue:
    return load_catalogue()


def _current(state) -> tuple[SectionRef, SectionTemplate]:
    ref = state["plan"][state["cursor"]]
    return ref, _catalogue().section(f"{ref.document}.{ref.section_id}")


def missing_required_facts(state) -> list[str]:
    """Les faits requis par la section courante qu'on n'a pas encore.

    Une clé présente compte comme connue même si sa valeur est nulle : « je ne
    sais pas » est une réponse, et la reposer serait une faute.
    """
    _, section = _current(state)
    return [f for f in section.faits_requis if f not in state["facts"]]


def question_batch(state) -> list[str]:
    """Ce qu'on demande à l'utilisateur pour la section courante.

    Les faits requis d'abord — sans eux la section ne s'écrit pas — puis les
    faits utiles dans les places qui restent. Un fait déjà connu n'y revient
    jamais, « je ne sais pas » compris : c'est une réponse.

    Un lot ne se forme que si un fait requis manque. Deux cas tombent donc
    dans le silence, et il vaut mieux les distinguer :
    - une section entièrement renseignée ne repose rien, ce qui est voulu ;
    - une section qui ne déclare **aucun** fait requis ne demande jamais rien,
      à aucun projet, jamais. Trois sont dans ce cas — `bp.risques_bp`,
      `cdc.risques_cdc` et `cdc.cadre_reponse` — avec quatre à cinq faits
      utiles chacune. Vérifié : leurs treize faits vivent tous ailleurs, dans
      une section qui, elle, en requiert, et aucun des sept faits dont les
      calculs dépendent n'est du nombre. C'est donc une perte de confort, pas
      une perte de tableau.
    """
    _, section = _current(state)
    required = [f for f in section.faits_requis if f not in state["facts"]]
    useful = [f for f in section.faits_utiles if f not in state["facts"]]
    if not required:
        return []
    return (required + useful)[:QUESTION_BATCH_SIZE]


# ------------------------------------------------------------- routage

def route_after_gaps(state) -> str:
    if missing_required_facts(state) and state["question_rounds"] < MAX_QUESTION_ROUNDS:
        return "formulate_questions"
    _, section = _current(state)
    return "compute" if section.calculs else "write"


def route_after_numbers(state) -> str:
    if state["problems"] and state["revisions"] < MAX_REVISIONS:
        return "write"
    return "critique"


def route_after_critique(state) -> str:
    score = state["score"] or 0
    if score < REWRITE_SCORE and state["revisions"] < MAX_REVISIONS:
        return "write"
    _, section = _current(state)
    if section.validation == "toujours" or score < _catalogue().review_threshold:
        return "review"
    return "save"


def route_after_save(state) -> str:
    return "analyse_gaps" if state["cursor"] < len(state["plan"]) else "coherence_check"


# --------------------------------------------------- nœuds déterministes

async def analyse_gaps(state) -> dict:
    """Point d'ancrage des arêtes conditionnelles, et rien d'autre.

    Il n'écrit pas la liste des manques dans l'état : elle est pure et
    instantanée à recalculer, alors qu'une clé de plus serait recopiée dans
    chacun des milliers de points de reprise d'un projet.
    """
    return {}


async def compute(state) -> dict:
    """Exécute les calculs que le template de la section déclare.

    Les hypothèses sont lues dans les faits, jamais demandées au modèle : le
    modèle structure, il ne calcule pas. Un calcul dont les hypothèses
    manquent est sauté et son absence se verra à la rédaction, en donnée à
    compléter.
    """
    _, section = _current(state)
    results: dict[str, Computation] = dict(state["computations"])
    for name in section.calculs:
        # `build_assumptions` est DANS le `try`, et ce n'est pas un détail de
        # style. Il ne rend `None` que sur un fait manquant ; sur un fait
        # présent mais hors des bornes pydantic de `finance.py` il lève une
        # `ValidationError`. Celle-ci est bien une `ValueError`, mais depuis
        # l'extérieur du `try` elle sortait du nœud et emportait le run — et
        # comme le point de reprise rejoue le même nœud, le projet restait
        # coincé pour de bon.
        #
        # Le cas n'a rien d'exotique : un projet freemium répond zéro au prix
        # unitaire, un projet déficitaire répond un coût variable supérieur au
        # prix. Rien ne valide les réponses en amont, `ask_questions` pose le
        # fait tel quel.
        try:
            assumptions = build_assumptions(name, state["facts"])
            if assumptions is None:
                # Les faits ne suffisent pas. Le tableau n'existera pas et le
                # texte portera une donnée à compléter — jamais une valeur par
                # défaut, qui serait un chiffre inventé de plus.
                continue
            results[name] = run_computation(name, assumptions)
        except ValueError:
            # Hypothèses aberrantes : une descente de marché incohérente, un
            # taux de marge nul, une réponse hors bornes. On n'écrit pas un
            # tableau faux, et surtout on n'emporte pas les neuf autres.
            continue
    return {"computations": results}


async def check_numbers(state) -> dict:
    """Déterministe, sans appel au modèle — d'où l'absence de `transport`
    dans la signature."""
    orphans = orphan_numbers(
        state["draft"] or [],
        state["facts"],
        list(state["computations"].values()),
    )
    return {"problems": [f"chiffre orphelin : {o.written} ({o.context.strip()})"
                         for o in orphans]}


async def save(state) -> dict:
    """Écrit la projection et avance le curseur.

    Le point de reprise reste la source de vérité (§4.6) : ce que cette
    fonction écrit sert à afficher un projet sans réhydrater le graphe.
    """
    ref, _ = _current(state)
    async with connection() as conn:
        await save_facts(conn, state["project_id"], state["facts"])
        await save_section(conn, state["project_id"], ref,
                           blocks=state["draft"] or [], statut="done",
                           note=state["score"], revisions=state["revisions"])
    return {"cursor": state["cursor"] + 1, "draft": None, "score": None,
            "problems": [], "revisions": 0, "question_rounds": 0}


# ---------------------------------------------- nœuds appelant le modèle

async def extract_facts(state, transport=None) -> dict:
    definitions = list(_catalogue().facts.values())
    reponse = await complete(
        "court",
        prompts.extraction_prompt(state["idea"], definitions),
        project_id=state["project_id"],
        schema=prompts.ExtractedFacts,
        transport=transport,
    )
    extraits = reponse.parsed.facts if reponse.parsed else []
    known_numbers = _catalogue().facts
    return {"facts": {
        e.fact_id: Fact(fact_id=e.fact_id, value=e.value,
                        source="deduced", confidence=e.confidence)
        for e in extraits
        # Le modèle peut inventer un identifiant ou proposer un fait qui ne
        # s'extrait pas : le réducteur ne les filtrerait pas, c'est ici.
        if e.fact_id in known_numbers and known_numbers[e.fact_id].deductible
    }}


async def formulate_questions(state, transport=None) -> dict:
    _, section = _current(state)
    reponse = await complete(
        "court",
        prompts.questions_prompt(section, question_batch(state), _catalogue()),
        project_id=state["project_id"],
        schema=prompts.ProposedQuestions,
        transport=transport,
    )
    # Une clé d'état dédiée (`pending_questions`), pas une entrée réservée
    # dans `computations` : voir le commentaire sur `EsquisseState`.
    return {"question_rounds": state["question_rounds"] + 1,
            "pending_questions": reponse.parsed}


async def write(state, transport=None) -> dict:
    """Rédige la section, en flux.

    Le texte diffusé est de la prose ; les blocs sont reconstruits à la fin
    par `parse_written_text`. C'est ce qui permet d'afficher la section
    pendant qu'elle s'écrit sans renoncer aux blocs typés dont l'export a
    besoin.
    """
    ref, section = _current(state)
    tables = [c for name, c in state["computations"].items()
              if isinstance(c, Computation) and name in section.calculs]
    profil = state["profil_cdc"] if ref.document == "cdc" else state["profil_bp"]
    pieces: list[str] = []
    async for event in stream(
        "redaction",
        prompts.writing_prompt(section, state["facts"], tables, profil,
                               _catalogue(), state["problems"]),
        project_id=state["project_id"],
        transport=transport,
    ):
        if isinstance(event, TextDelta):
            pieces.append(event.text)
        elif isinstance(event, StreamRestart):
            # Le flux est reparti entier sur le fournisseur suivant (§5.2) :
            # ce qui avait déjà été accumulé n'est plus la section, sous
            # peine de coller un faux départ devant le texte relancé.
            pieces = []
        elif isinstance(event, StreamDone):
            pass
    return {"draft": prompts.parse_written_text("".join(pieces), tables),
            "revisions": state["revisions"] + 1}


async def critique(state, transport=None) -> dict:
    _, section = _current(state)
    reponse = await complete(
        "court",
        prompts.critique_prompt(section, state["draft"] or []),
        project_id=state["project_id"],
        schema=prompts.Critique,
        transport=transport,
    )
    verdict = reponse.parsed
    return {"score": verdict.score if verdict else 0,
            "problems": verdict.problems if verdict else []}


async def coherence_check(state, transport=None) -> dict:
    """Le seul appel sur la route `grand_contexte` : les deux documents
    entiers, parce qu'une incohérence se voit entre eux."""
    from app.agent.projections import load_sections

    async with connection() as conn:
        sections = await load_sections(conn, state["project_id"])
    reponse = await complete(
        "grand_contexte",
        prompts.coherence_prompt([
            (f"{s['document']}.{s['section_id']}", s["blocks"]) for s in sections
        ]),
        project_id=state["project_id"],
        schema=prompts.FoundInconsistencies,
        transport=transport,
    )
    found = reponse.parsed.inconsistencies if reponse.parsed else []
    return {"inconsistencies": [i.model_dump() for i in found]}
