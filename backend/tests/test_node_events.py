from uuid import uuid4

import pytest_asyncio

from app.agent import nodes
from app.agent.state import Paragraph
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
        await nodes.critique(
            _state(project, draft=[Paragraph(text="Un texte de section.")]),
            transport=FakeTransport())
        received = await _collect(events, 1)
    assert [e.name for e in received] == ["score"]
    assert "score" in received[0].data
    assert "problems" in received[0].data


async def test_saving_publishes_the_section_and_the_progress(project):
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


async def test_a_restart_is_published_between_the_false_start_and_the_real_text(project):
    """L'ordre est le contrat, autant que la charge utile.

    Publié trop tôt, le navigateur effacerait du texte valide ; trop tard, il
    laisserait le faux départ collé devant le vrai. Et sans `document` ni
    `section_id`, il ne saurait pas quelle section vider — un projet `both`
    en a soixante.

    `FakeTransport` ne rompt jamais un flux : ce chemin ne s'atteint qu'avec
    le simulé sous script de `test_nodes.py`.
    """
    from app.llm.errors import ProviderUnavailable
    from tests.test_nodes import _RestartingTransport

    stub = _RestartingTransport({
        ("gemini", "gemini-3.1-flash-lite"): [
            "Un faux départ jamais gardé.",
            ProviderUnavailable("gemini", "erreur", "flux rompu"),
        ],
        ("mistral", "ministral-8b-latest"): ["Le texte définitif de la section."],
    })
    async with subscribe(project) as events:
        await nodes.write(_state(project), transport=stub)
        received = await _collect(events, 200)

    names = [e.name for e in received]
    assert "section_restart" in names, "la reprise de flux n'a pas été publiée"
    cut = names.index("section_restart")
    before = "".join(e.data["text"] for e in received[:cut] if e.name == "token")
    after = "".join(e.data["text"] for e in received[cut + 1:] if e.name == "token")
    assert "faux départ" in before, "le faux départ n'a pas été publié avant la reprise"
    assert "définitif" in after, "le vrai texte n'a pas été publié après la reprise"

    restart = received[cut]
    ref = _state(project)["plan"][0]
    assert restart.data == {"document": ref.document, "section_id": ref.section_id}


async def test_no_empty_fragment_is_ever_published(project):
    """Un `token` vide n'est pas anodin.

    Il signifierait que la publication a quitté la branche `TextDelta` et
    s'applique aussi aux trames de service — reprise de flux, fin de flux.
    Le navigateur recevrait alors des fragments qui ne sont pas du texte, et
    rien dans la concaténation ne le dirait : coller des chaînes vides ne
    change pas le résultat, c'est pourquoi l'assertion sur le texte assemblé
    ne suffit pas à garder cette propriété.
    """
    async with subscribe(project) as events:
        await nodes.write(_state(project), transport=FakeTransport())
        received = await _collect(events, 200)

    tokens = [e for e in received if e.name == "token"]
    assert tokens
    assert all(e.data["text"] for e in tokens), "un fragment vide a été publié"


async def test_the_progress_total_follows_the_state_plan_and_not_the_catalogue(project):
    """`total` vient de `state["plan"]`, et l'écart compte.

    Les deux expressions donnent le même nombre dans le cas nominal, ce qui
    rendait ce contrat intestable : la fixture a toujours un plan qui coïncide
    avec ce qu'une relecture du catalogue produirait. On tronque donc le plan,
    et les deux sources divergent.

    Ce n'est pas une contorsion de test : le plan de l'état est ce qui reste
    juste quand il a été réduit — une reprise partielle, une section rouverte
    — alors qu'une relecture du catalogue rendrait toujours la liste entière
    et afficherait une progression fausse à l'utilisateur.
    """
    state = _state(project, draft=[Paragraph(text="Un texte.")], score=9)
    state["plan"] = state["plan"][:3]

    async with subscribe(project) as events:
        await nodes.save(state)
        received = await _collect(events, 2)

    progress = next(e for e in received if e.name == "progress")
    assert progress.data["total"] == 3, (
        "`total` ne vient pas de `state[\"plan\"]` mais d'une relecture du "
        "catalogue, qui ignore un plan réduit"
    )


async def test_the_published_score_matches_the_returned_one_when_nothing_parses(project):
    """Un navigateur à qui l'on montre une note que le graphe n'a pas suivie
    est un navigateur à qui l'on ment.

    Le chemin de repli — le modèle rend quelque chose d'inexploitable — n'est
    exercé par aucun test : `FakeTransport` rend toujours un schéma valide.
    Or ce repli n'est pas théorique : une note de zéro passe sous
    `REWRITE_SCORE` et renvoie donc la section en réécriture.
    """
    from app.llm.types import Completion

    class _UnparsableTransport(FakeTransport):
        async def chat(self, provider, model, messages, *, schema=None):
            return Completion(text="{}", provider=provider.name, model=model,
                              tokens=1, parsed=None)

    async with subscribe(project) as events:
        maj = await nodes.critique(
            _state(project, draft=[Paragraph(text="Un texte.")]),
            transport=_UnparsableTransport())
        received = await _collect(events, 1)

    assert maj["score"] == 0 and maj["problems"] == []
    published = next(e for e in received if e.name == "score")
    assert published.data["score"] == maj["score"]
    assert published.data["problems"] == maj["problems"]
