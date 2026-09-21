from uuid import uuid4

import pytest_asyncio

from app.agent import nodes
from app.agent.templates import load_catalogue
from app.core.db import connection
from app.llm.fake import FakeTransport
from app.projects.repository import create_project
from app.runs.events import subscribe

CATALOGUE = load_catalogue()


@pytest_asyncio.fixture
async def project(migrated_db):
    # Même motif que `tests/test_nodes.py::project` : les nœuds écrivent dans
    # `llm_usage` et `sections`, qui portent une clé étrangère vers `projects`.
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) "
                "values (%s, 'x', true) returning id",
                (f"events-{uuid4()}@exemple.fr",),
            )
            user_id = (await cur.fetchone())[0]
        project_id = await create_project(
            conn, user_id, nom="CoachDom", documents="cdc",
            profil_cdc="consultation", profil_bp=None,
            thread_id=f"thread-{uuid4()}", templates_version="0.1",
        )
    yield str(project_id)


def _state(project_id, **overrides):
    plan = CATALOGUE.plan_for("cdc", "consultation", None)
    base = {
        "project_id": project_id,
        "documents": "cdc",
        "profil_cdc": "consultation",
        "profil_bp": None,
        "idea": "Une plateforme de coaching sportif à domicile.",
        "facts": {},
        "plan": plan,
        "cursor": 0,
        "draft": None,
        "score": None,
        "problems": [],
        "revisions": 0,
        "question_rounds": 0,
        "computations": {},
        "pending_questions": None,
        "inconsistencies": [],
    }
    base.update(overrides)
    return base


async def _collect(events, stop_after):
    """Tout ce qui arrive jusqu'à en avoir `stop_after`, sans attendre
    indéfiniment si le nœud n'en publie pas assez."""
    import asyncio

    collected = []
    try:
        while len(collected) < stop_after:
            collected.append(await asyncio.wait_for(anext(events), timeout=1))
    except asyncio.TimeoutError:
        pass
    return collected


async def test_writing_publishes_its_tokens(project):
    async with subscribe(project) as events:
        await nodes.write(_state(project), transport=FakeTransport())
        received = await _collect(events, 200)
    tokens = [e for e in received if e.name == "token"]
    assert tokens, "la rédaction n'a publié aucun fragment"
    assert all("text" in e.data for e in tokens)
    # Le texte publié est celui qui part dans le brouillon, pas un résumé.
    assert "".join(e.data["text"] for e in tokens)


async def test_the_critique_publishes_its_score(project):
    async with subscribe(project) as events:
        from app.agent.state import Paragraph

        await nodes.critique(
            _state(project, draft=[Paragraph(text="Un texte de section.")]),
            transport=FakeTransport())
        received = await _collect(events, 1)
    assert [e.name for e in received] == ["score"]
    assert "score" in received[0].data
    assert "problems" in received[0].data


async def test_saving_publishes_the_section_and_the_progress(project):
    from app.agent.state import Paragraph

    async with subscribe(project) as events:
        await nodes.save(_state(project, draft=[Paragraph(text="Un texte.")],
                                score=9))
        received = await _collect(events, 2)
    names = [e.name for e in received]
    assert names == ["section_saved", "progress"]
    saved, progress = received
    assert saved.data["document"] == "cdc"
    assert saved.data["section_id"] == CATALOGUE.plan_for(
        "cdc", "consultation", None)[0].section_id
    # Le curseur publié est celui d'APRÈS l'avancée : le front affiche une
    # progression, pas la section qu'il vient de quitter.
    assert progress.data["cursor"] == 1
    assert progress.data["total"] == len(
        CATALOGUE.plan_for("cdc", "consultation", None))


async def test_a_node_runs_identically_with_nobody_listening(project):
    """Le test qui protège les 374 autres.

    Aucun abonné : `publish` est sans effet, et le nœud doit rendre
    exactement ce qu'il rendait avant cette tâche.
    """
    maj = await nodes.write(_state(project), transport=FakeTransport())
    assert maj["draft"]
    assert maj["revisions"] == 1
