import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.types import Command

from app.agent import nodes, prompts
from app.agent.checkpointer import close_checkpointer
from app.agent.graph import compiled_graph, initial_state
from app.agent.projections import load_sections
from app.agent.templates import load_catalogue
from app.core.db import connection
from app.projects.repository import create_project

IDEA = "Une plateforme de coaching sportif à domicile."


@pytest_asyncio.fixture
async def project(migrated_db, monkeypatch):
    """Même montage que `tests/test_graph.py::project` : un projet `cdc`
    au profil `cadrage`, rédigé par le modèle simulé."""
    monkeypatch.setenv("ESQUISSE_FAKE_LLM", "true")
    from app.core import config
    config.settings.cache_clear()
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id", (f"r-{uuid4()}@exemple.fr",))
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="cdc",
            profil_cdc="cadrage", profil_bp=None,
            thread_id=f"thread-{uuid4()}", templates_version="0.1")
    yield project_id
    await close_checkpointer()
    config.settings.cache_clear()


async def _drive(graph, config, graph_input, *, review=None, rulings=None):
    """Mène le run jusqu'au bout et rend les interruptions rencontrées.

    `review` et `rulings` sont des fonctions asynchrones appelées sur la
    charge utile de l'interruption, AVANT la reprise : c'est là qu'un test
    pose ses sentinelles. Sans elles, on accepte chaque relecture et on
    n'arbitre rien.
    """
    seen = []
    for _ in range(300):  # borne : une boucle infinie doit échouer, pas pendre
        await graph.ainvoke(graph_input, config=config)
        snapshot = await graph.aget_state(config)
        if not snapshot.interrupts:
            return seen
        payload = snapshot.interrupts[0].value
        seen.append(payload)
        if payload["kind"] == "questions":
            answer = {q["fact_id"]: "une réponse" for q in payload["questions"]}
        elif payload["kind"] == "review":
            answer = await review(payload) if review else {"action": "accept"}
        else:
            answer = await rulings(payload) if rulings else []
        graph_input = Command(resume=answer)
    pytest.fail("le run n'a pas convergé en 300 reprises")


async def _mark_every_section(project_id) -> None:
    """Pose une note sentinelle sur toutes les sections déjà écrites.

    `save` réécrit la note avec celle de l'auto-critique, entre 0 et 10 : une
    section qui repasse par `save` perd donc la sentinelle, et c'est ce qui
    dit, sans ambiguïté, lesquelles ont été réécrites.
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update sections set note = -1 where project_id = %s", (project_id,))


async def _rewritten(project_id) -> set[str]:
    async with connection() as conn:
        sections = await load_sections(conn, project_id)
    return {f"{s['document']}.{s['section_id']}" for s in sections if s["note"] != -1}


def _spy_on_writing(monkeypatch) -> list[list[str]]:
    """Relève le `problems` de chaque appel au rédacteur."""
    seen: list[list[str]] = []
    original = nodes.prompts.writing_prompt

    def spy(*args):
        seen.append(list(args[5]))
        return original(*args)

    monkeypatch.setattr(nodes.prompts, "writing_prompt", spy)
    return seen


def test_the_rework_queue_follows_the_plan_and_drops_what_is_not_in_it():
    plan = load_catalogue().plan_for("cdc", "cadrage", None)
    ids = [nodes.qualified(ref) for ref in plan]
    # `cdc.cadre_reponse` n'existe qu'au profil « consultation » : hors de ce
    # plan-ci, comme une section qu'un modèle aurait inventée.
    wanted = [ids[3], "cdc.cadre_reponse", ids[1], "bp.inventee"]
    assert nodes.rework_queue(plan, wanted) == [ids[1], ids[3]]


async def test_an_arbitration_rewrites_exactly_the_sections_it_names(project, monkeypatch):
    written = _spy_on_writing(monkeypatch)
    named: list[str] = []

    async def rule(payload):
        named.extend(payload["inconsistencies"][0]["sections"])
        await _mark_every_section(project)
        written.clear()
        return [{"index": 0, "decision": "corriger", "consigne": "Aligner les dates"},
                *[{"index": i, "decision": "ignorer"}
                  for i in range(1, len(payload["inconsistencies"]))]]

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await _drive(graph, config,
                 initial_state(str(project), "cdc", "cadrage", None, IDEA),
                 rulings=rule)

    assert named, "le simulé doit nommer au moins une section du plan"
    assert await _rewritten(project) == set(named)
    assert any("Aligner les dates" in problem
               for problems in written for problem in problems)
    values = (await graph.aget_state(config)).values
    assert values["cursor"] == len(values["plan"])
    assert values["reworking"] is False
    assert values["rework"] == []


async def test_ignoring_every_inconsistency_rewrites_nothing(project):
    async def rule(payload):
        await _mark_every_section(project)
        return [{"index": i, "decision": "ignorer"}
                for i in range(len(payload["inconsistencies"]))]

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await _drive(graph, config,
                 initial_state(str(project), "cdc", "cadrage", None, IDEA),
                 rulings=rule)

    assert await _rewritten(project) == set()


async def test_malformed_rulings_rewrite_nothing_and_do_not_crash(project):
    async def rule(payload):
        await _mark_every_section(project)
        return [
            {"index": 99, "decision": "corriger"},       # hors bornes
            "n'importe quoi",                             # pas un dictionnaire
            {"index": True, "decision": "corriger"},      # un booléen n'est pas un index
            {"index": 0, "decision": "valider"},          # décision inconnue
            {"decision": "corriger"},                     # index absent
        ]

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await _drive(graph, config,
                 initial_state(str(project), "cdc", "cadrage", None, IDEA),
                 rulings=rule)

    assert await _rewritten(project) == set()


async def test_a_rework_on_a_finished_thread_rewrites_its_queue_and_nothing_else(
        project, monkeypatch):
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await _drive(graph, config,
                 initial_state(str(project), "cdc", "cadrage", None, IDEA))
    plan = (await graph.aget_state(config)).values["plan"]
    # Donnés dans le désordre : la file suit l'ordre du plan, pas la demande.
    targets = [nodes.qualified(plan[5]), nodes.qualified(plan[2])]
    await _mark_every_section(project)

    calls: list[str] = []

    async def no_extraction(state, transport=None):
        calls.append("extract_facts")
        return {}

    async def no_coherence(state, transport=None):
        calls.append("coherence_check")
        return {"inconsistencies": []}

    events = []
    monkeypatch.setattr(nodes, "extract_facts", no_extraction)
    monkeypatch.setattr(nodes, "coherence_check", no_coherence)
    monkeypatch.setattr(nodes, "publish", lambda project_id, event: events.append(event))
    written = _spy_on_writing(monkeypatch)

    # Recompilé APRÈS les remplacements : `build_graph` lit les nœuds au
    # moment où il construit le graphe.
    graph = await compiled_graph()
    await _drive(graph, config, {
        "rework": targets,
        "rework_notes": {targets[1]: ["refaire l'introduction"]},
    })

    assert await _rewritten(project) == set(targets)
    assert calls == []
    assert any("refaire l'introduction" in p for problems in written for p in problems)
    # Une section sans consigne reçoit tout de même une raison d'être reprise.
    assert any(nodes.REOPENED_WITHOUT_NOTE in problems for problems in written)
    progress = [e.data for e in events if e.name == "progress"]
    assert [p["reecriture"] for p in progress] == [1, 0]
    values = (await graph.aget_state(config)).values
    assert values["cursor"] == len(values["plan"])
    assert values["rework"] == [] and values["reworking"] is False


async def test_a_normal_run_publishes_no_rework_count(project, monkeypatch):
    events = []
    monkeypatch.setattr(nodes, "publish", lambda project_id, event: events.append(event))
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await _drive(graph, config,
                 initial_state(str(project), "cdc", "cadrage", None, IDEA))
    progress = [e.data for e in events if e.name == "progress"]
    assert progress and all("reecriture" not in p for p in progress)


async def test_skipping_a_review_saves_the_section_skipped(project):
    skipped: list[str] = []

    async def review(payload):
        if not skipped:
            skipped.append(payload["section"])
            return {"action": "skip"}
        return {"action": "accept"}

    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    await _drive(graph, config,
                 initial_state(str(project), "cdc", "cadrage", None, IDEA),
                 review=review)

    assert skipped, "le plan « cadrage » compte des sections à relecture obligatoire"
    async with connection() as conn:
        sections = await load_sections(conn, project)
    statuses = {f"{s['document']}.{s['section_id']}": s["statut"] for s in sections}
    assert statuses[skipped[0]] == "skipped"
    assert all(statut == "done"
               for key, statut in statuses.items() if key != skipped[0])


async def test_the_review_payload_carries_the_draft_blocks(project):
    graph = await compiled_graph()
    config = {"configurable": {"thread_id": f"t-{project}"}}
    seen = await _drive(graph, config,
                        initial_state(str(project), "cdc", "cadrage", None, IDEA))
    reviews = [p for p in seen if p["kind"] == "review"]
    assert reviews
    for payload in reviews:
        assert payload["blocks"], "une relecture sans texte n'a rien à relire"
        assert all(isinstance(b, dict) and "kind" in b for b in payload["blocks"])
        json.dumps(payload["blocks"])  # doit traverser le flux SSE tel quel


async def test_the_coherence_check_drops_sections_outside_the_plan(project, monkeypatch):
    plan = load_catalogue().plan_for("cdc", "cadrage", None)
    inside = nodes.qualified(plan[0])

    async def fake_complete(*args, **kwargs):
        return SimpleNamespace(parsed=prompts.FoundInconsistencies(inconsistencies=[
            prompts.FoundInconsistency(
                kind="date", description="deux dates",
                # Une section inventée, et une vraie section du business
                # plan — qui existe au catalogue, mais pas dans ce plan.
                sections=[inside, "cdc.inexistante", "bp.probleme_solution"],
                proposal=None),
        ]))

    monkeypatch.setattr(nodes, "complete", fake_complete)
    result = await nodes.coherence_check({"project_id": str(project), "plan": plan})
    assert result["inconsistencies"][0]["sections"] == [inside]
