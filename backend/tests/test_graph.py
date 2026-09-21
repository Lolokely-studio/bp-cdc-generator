from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.types import Command

from app.agent.checkpointer import close_checkpointer, purge_checkpoints
from app.agent.graph import build_graph, compiled_graph, initial_state
from app.agent.projections import load_sections
from app.core.db import connection
from app.projects.repository import create_project


@pytest_asyncio.fixture
async def project(migrated_db, monkeypatch):
    # Le graphe ne reçoit pas de transport : la passerelle lit le réglage.
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config
    config.settings.cache_clear()
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id", (f"g-{uuid4()}@exemple.fr",))
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="cdc",
            profil_cdc="cadrage", profil_bp=None,
            thread_id=f"thread-{uuid4()}", templates_version="0.1")
    yield project_id
    await close_checkpointer()
    config.settings.cache_clear()


@pytest_asyncio.fixture
async def project_bp(migrated_db, monkeypatch):
    # Le même montage que `project`, mais sur le business plan : c'est le
    # seul document dont des sections déclarent des calculs.
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config
    config.settings.cache_clear()
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id", (f"g-{uuid4()}@exemple.fr",))
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="bp",
            profil_cdc=None, profil_bp="banque",
            thread_id=f"thread-{uuid4()}", templates_version="0.1")
    yield project_id
    await close_checkpointer()
    config.settings.cache_clear()


def test_the_graph_compiles_with_every_edge_of_the_spec():
    graph = build_graph().compile()
    node_names = set(graph.get_graph().nodes)
    assert {"extract_facts", "analyse_gaps", "formulate_questions", "ask_questions",
            "compute", "write", "check_numbers", "critique", "review", "save",
            "coherence_check", "arbitrate"} <= node_names


async def test_a_run_reaches_its_first_interruption(project):
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await graph.ainvoke(initial_state(str(project), "cdc", "cadrage", None,
                                       "Une plateforme de coaching à domicile."), config=config)
    snapshot = await graph.aget_state(config)
    assert snapshot.interrupts, "le graphe devrait s'arrêter pour poser ses questions"
    assert snapshot.interrupts[0].value["kind"] in {"questions", "review"}


async def test_a_full_run_writes_every_section_of_the_plan(project):
    """Le cœur de ce plan : les sections du plan « cdc » / « cadrage »
    rédigées de bout en bout, hors ligne, en reprenant à chaque interruption.

    Le brief attendait quinze sections ; le catalogue de la tâche 3 (déjà
    committé) réserve `cadre_reponse` au seul profil « consultation », donc
    le plan « cadrage » n'en compte que quatorze — vérifié directement contre
    `load_catalogue().cdc.sections` avant d'écrire ce test. Le nombre attendu
    est donc dérivé du catalogue plutôt que d'un compte figé en dur : si le
    catalogue change à nouveau, ce test le suivra au lieu de mentir.
    """
    from app.agent.templates import load_catalogue

    expected_sections = len(
        [s for s in load_catalogue().cdc.sections if "cadrage" in s.profils]
    )

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    graph_input = initial_state(str(project), "cdc", "cadrage", None,
                           "Une plateforme de coaching sportif à domicile.")

    for _ in range(200):  # borne de sécurité : une boucle infinie doit échouer, pas pendre
        await graph.ainvoke(graph_input, config=config)
        snapshot = await graph.aget_state(config)
        if not snapshot.interrupts:
            break
        payload = snapshot.interrupts[0].value
        if payload["kind"] == "questions":
            graph_input = Command(resume={q["fact_id"]: "une réponse" for q in payload["questions"]})
        elif payload["kind"] == "review":
            graph_input = Command(resume={"action": "accept"})
        else:
            graph_input = Command(resume=[])
    else:
        pytest.fail("le run n'a pas convergé en 200 reprises")

    async with connection() as conn:
        sections = await load_sections(conn, project)
    assert len(sections) == expected_sections
    assert all(s["statut"] == "done" for s in sections)
    assert all(s["blocks"] for s in sections)


async def test_a_run_resumes_where_it_stopped(project):
    # Le point de reprise fait foi : un nouveau graphe compilé sur le même
    # thread retrouve l'état, sans rien réexécuter.
    config = {"configurable": {"thread_id": f"t-{project}"}}
    first = await compiled_graph()
    await first.ainvoke(initial_state(str(project), "cdc", "cadrage", None, "Une idée."),
                          config=config)
    before = (await first.aget_state(config)).values["cursor"]

    second = await compiled_graph()
    after = (await second.aget_state(config)).values["cursor"]
    assert after == before


async def test_purging_keeps_the_last_checkpoint(project):
    config = {"configurable": {"thread_id": f"t-{project}"}}
    graph = await compiled_graph()
    await graph.ainvoke(initial_state(str(project), "cdc", "cadrage", None, "Une idée."),
                         config=config)
    before = (await graph.aget_state(config)).values["cursor"]

    deleted = await purge_checkpoints(f"t-{project}")
    assert deleted > 0

    # Ce que la purge doit préserver : la capacité à reprendre.
    after = (await graph.aget_state(config)).values["cursor"]
    assert after == before


# Des réponses chiffrées, par identifiant de fait. Le simulé répond « une
# réponse » à tout : sur un montant cela ne donne aucun nombre, donc aucune
# hypothèse, donc aucun tableau. Pour parcourir la chaîne il faut répondre en
# chiffres, comme un porteur de projet le ferait.
_NUMERIC_ANSWERS = {
    "prix_moyen_unite": 45,
    "cout_variable_unitaire": 15,
    "volume_ventes_an1": 4_000,
    "charges_fixes_mensuelles": 3_000,
    "masse_salariale_an1": 60_000,
    "hypothese_croissance": 0.30,
    "investissements_initiaux": 20_000,
    "budget_developpement": 40_000,
    "tresorerie_securite": 15_000,
    "apport_fondateurs": 30_000,
    "emprunt_montant": 50_000,
    "emprunt_duree": 60,
    "taux_interet_emprunt": 0.04,
    "aides_subventions": 4_000,
    "delai_paiement_clients": 30,
    "taille_marche_tam": 300_000_000,
    "taille_marche_sam": 90_000_000,
    "taille_marche_som": 4_500_000,
}


async def test_a_business_plan_run_produces_tables(project_bp):
    """Le chemin que l'autre exécution ne touche pas.

    Le cahier des charges en profil cadrage ne déclare aucun calcul : son
    exécution n'exerce ni la construction des hypothèses, ni les calculs, ni
    le repère de tableau. Ce test est le seul endroit où la chaîne complète
    est parcourue — un fait chiffré, une hypothèse construite, un calcul, un
    repère placé par le modèle, un bloc `Table` dans la section enregistrée.
    """
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project_bp}"}}
    graph_input = initial_state(str(project_bp), "bp", None, "banque",
                                "Une plateforme de coaching sportif à domicile.")

    for _ in range(300):
        await graph.ainvoke(graph_input, config=config)
        snapshot = await graph.aget_state(config)
        if not snapshot.interrupts:
            break
        payload = snapshot.interrupts[0].value
        if payload["kind"] == "questions":
            graph_input = Command(resume={
                q["fact_id"]: _NUMERIC_ANSWERS.get(q["fact_id"], "une réponse")
                for q in payload["questions"]
            })
        elif payload["kind"] == "review":
            graph_input = Command(resume={"action": "accept"})
        else:
            graph_input = Command(resume=[])
    else:
        pytest.fail("le run n'a pas convergé en 300 reprises")

    async with connection() as conn:
        sections = await load_sections(conn, project_bp)

    assert sections, "aucune section enregistrée"
    tables = [b for s in sections for b in s["blocks"] if b.kind == "table"]
    # Avant la règle du lot, quatre tableaux sortaient sur dix calculs
    # possibles : les faits qui alimentent les six autres n'étaient jamais
    # demandés. Le seuil est là pour que la régression se voie.
    assert len(tables) >= 6, (
        f"{len(tables)} tableaux seulement : les faits utiles ne sont "
        "probablement plus demandés"
    )
    # Chaque tableau porte un titre et des lignes : un tableau vide serait un
    # trou dans le document, pas une réussite.
    for table in tables:
        assert table.title
        assert table.rows


async def test_a_review_that_asks_for_a_rewrite_sends_the_section_back(project):
    """La branche que personne n'emprunte.

    Toutes les autres reprises acceptent. Si la réécriture cessait un jour de
    repartir — des `revisions` non remises à zéro, des problèmes perdus — la
    suite resterait verte.
    """
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-rewrite-{project}"}}
    graph_input = initial_state(str(project), "cdc", "cadrage", None, "Une idée.")

    demande_faite = False
    for _ in range(200):
        await graph.ainvoke(graph_input, config=config)
        snapshot = await graph.aget_state(config)
        if not snapshot.interrupts:
            break
        payload = snapshot.interrupts[0].value
        if payload["kind"] == "questions":
            graph_input = Command(resume={q["fact_id"]: "une réponse"
                                          for q in payload["questions"]})
        elif payload["kind"] == "review":
            if not demande_faite:
                # Une seule fois : la section doit repartir, puis converger.
                demande_faite = True
                graph_input = Command(resume={
                    "action": "rewrite",
                    "problems": ["Le premier objectif n'est pas mesurable."],
                })
            else:
                graph_input = Command(resume={"action": "accept"})
        else:
            graph_input = Command(resume=[])
    else:
        pytest.fail("le run n'a pas convergé après une demande de réécriture")

    assert demande_faite, "aucune relecture n'a été proposée, le test n'a rien éprouvé"
    async with connection() as conn:
        sections = await load_sections(conn, project)
    assert sections, "la demande de réécriture a fait perdre les sections"
    assert all(s["statut"] == "done" for s in sections)


async def test_an_answer_outside_the_catalogue_never_becomes_a_fact():
    """La seconde porte d'entrée des faits, longtemps restée sans loquet.

    `extract_facts` filtre ce que le modèle propose ; `ask_questions` ne
    filtrait rien. Une paire clé/valeur arbitraire devenait un fait
    `source="user"`, donc protégé contre toute correction, puis persisté,
    puis compté parmi les « nombres connus » du vérificateur — de sorte
    qu'un chiffre inventé cessait d'être signalé comme orphelin.
    """
    from unittest.mock import patch

    from app.agent import graph as graph_module

    reponses = {"prix_moyen_unite": 45, "fait_invente": 999_999.0}
    with patch.object(graph_module, "interrupt", lambda _: reponses):
        maj = await graph_module.ask_questions(
            {"pending_questions": None, "plan": [], "cursor": 0})

    assert "prix_moyen_unite" in maj["facts"]
    assert "fait_invente" not in maj["facts"], (
        "une clé hors catalogue est entrée dans les faits"
    )


async def test_a_rewrite_without_a_reason_still_sends_the_section_back():
    """Un champ libre laissé vide suffisait à valider la section.

    `_route_after_review` route sur `problems` : une liste vide envoyait vers
    `save`, donc marquait la section terminée, au moment précis où
    l'utilisateur venait de dire qu'elle ne l'était pas.
    """
    from unittest.mock import patch

    from app.agent import graph as graph_module
    from app.agent.state import SectionRef

    state = {"plan": [SectionRef(document="cdc", section_id="contexte_objectifs",
                                 order=1)],
             "cursor": 0, "score": 5, "problems": []}
    for demande in ({"action": "rewrite"},
                    {"action": "rewrite", "problems": []}):
        with patch.object(graph_module, "interrupt", lambda _, d=demande: d):
            maj = await graph_module.review(state)
        assert maj["problems"], f"{demande} a rendu une liste vide"
        assert graph_module._route_after_review(maj) == "write"

    with patch.object(graph_module, "interrupt", lambda _: {"action": "accept"}):
        maj = await graph_module.review(state)
    assert maj["problems"] == []
    assert graph_module._route_after_review(maj) == "save"


def test_the_writing_prompt_carries_the_problems_to_correct():
    """`problems` avait trois producteurs et deux lecteurs, tous deux des
    routeurs. Le rédacteur ne le recevait pas : une réécriture réémettait le
    prompt à l'identique, et rendait donc le même brouillon."""
    from app.agent.prompts import writing_prompt
    from app.agent.templates import load_catalogue

    catalogue = load_catalogue()
    section = catalogue.section("cdc.contexte_objectifs")
    sans = writing_prompt(section, {}, [], "cadrage", catalogue)
    avec = writing_prompt(section, {}, [], "cadrage", catalogue,
                          ["Le premier objectif n'est pas mesurable."])

    assert sans != avec, "le prompt de réécriture est identique au premier jet"
    assert "Le premier objectif n'est pas mesurable." in avec[1].content
