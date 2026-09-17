from pathlib import Path
from uuid import uuid4

import pytest

from esquisse.db import connection
from esquisse.projects.repository import (
    ProjectNotFound,
    create_project,
    project_for_user,
)


async def _make_user(email: str):
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into users (email, password_hash, is_active) values (%s, 'x', true) returning id",
                (email,),
            )
            return (await cur.fetchone())[0]


async def test_owner_reads_own_project(migrated_db):
    uid = await _make_user(f"prop-{uuid4()}@exemple.fr")
    async with connection() as conn:
        pid = await create_project(conn, uid, "CoachDom", "both", "consultation", "banque",
                                 f"thread-{uuid4()}", "0.1")
        projet = await project_for_user(conn, pid, uid)
    assert projet["nom"] == "CoachDom"


async def test_other_user_cannot_find_it(migrated_db):
    """Introuvable, pas interdit : répondre 403 révélerait que le projet existe."""
    proprietaire = await _make_user(f"a-{uuid4()}@exemple.fr")
    intrus = await _make_user(f"b-{uuid4()}@exemple.fr")
    async with connection() as conn:
        pid = await create_project(conn, proprietaire, "Privé", "cdc", "cadrage", None,
                                 f"thread-{uuid4()}", "0.1")
        with pytest.raises(ProjectNotFound):
            await project_for_user(conn, pid, intrus)


async def test_missing_project_raises_same_error(migrated_db):
    uid = await _make_user(f"c-{uuid4()}@exemple.fr")
    async with connection() as conn:
        with pytest.raises(ProjectNotFound):
            await project_for_user(conn, uuid4(), uid)


def test_no_projects_query_outside_repository():
    """Garde-fou structurel : le cloisonnement ne vaut que si personne ne
    contourne le dépôt. Ce test casse dès qu'une route écrit son propre SQL."""
    racine = Path(__file__).resolve().parents[1] / "esquisse"
    autorise = racine / "projects" / "repository.py"
    coupables = [
        f for f in racine.rglob("*.py")
        if f != autorise and "from projects" in f.read_text(encoding="utf-8").lower()
    ]
    assert coupables == [], f"SQL sur projects hors du dépôt : {coupables}"
