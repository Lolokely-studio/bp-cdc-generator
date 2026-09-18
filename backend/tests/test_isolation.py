import re
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.db import connection
from app.projects.repository import (
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
        pid = await create_project(
            conn, uid, nom="CoachDom", documents="both", profil_cdc="consultation",
            profil_bp="banque", thread_id=f"thread-{uuid4()}", templates_version="0.1",
        )
        project = await project_for_user(conn, pid, uid)
    assert project["nom"] == "CoachDom"


async def test_other_user_cannot_find_it(migrated_db):
    """Introuvable, pas interdit : répondre 403 révélerait que le projet existe."""
    owner = await _make_user(f"a-{uuid4()}@exemple.fr")
    intruder = await _make_user(f"b-{uuid4()}@exemple.fr")
    async with connection() as conn:
        pid = await create_project(
            conn, owner, nom="Privé", documents="cdc", profil_cdc="cadrage",
            profil_bp=None, thread_id=f"thread-{uuid4()}", templates_version="0.1",
        )
        with pytest.raises(ProjectNotFound):
            await project_for_user(conn, pid, intruder)


async def test_missing_project_raises_same_error(migrated_db):
    uid = await _make_user(f"c-{uuid4()}@exemple.fr")
    async with connection() as conn:
        with pytest.raises(ProjectNotFound):
            await project_for_user(conn, uuid4(), uid)


# Chercher « from projects » au caractère près ne couvre qu'une seule façon
# d'écrire la requête. Les jointures — la forme la plus probable pour lire les
# projets à côté des sections — ne contiennent jamais cette suite de mots.
_PROJECTS_TABLE = re.compile(r"\b(from|join|into|update)\s+(?:public\.)?projects\b")


def _touches_projects_table(source: str) -> bool:
    """Cherche une référence SQL à la table `projects`, quelle que soit sa mise
    en forme. Les sauts de ligne et espaces multiples sont ramenés à un espace
    unique avant la recherche, sinon une requête écrite sur plusieurs lignes
    passerait à travers."""
    return bool(_PROJECTS_TABLE.search(re.sub(r"\s+", " ", source.lower())))


@pytest.mark.parametrize(
    "snippet",
    [
        "select * from projects where id = 1",
        "select *\n  from\n  projects\n where id = 1",
        "select * from public.projects",
        "select s.* from sections s join projects p on p.id = s.project_id",
        "update projects set nom = 'x'",
        "insert into projects (nom) values ('x')",
    ],
)
def test_the_guard_catches_every_shape(snippet):
    """On teste le garde-fou lui-même. Un garde-fou qu'on peut franchir sans
    s'en apercevoir est pire que pas de garde-fou : il fabrique de la
    confiance. La jointure est le cas qui compte, parce que c'est la forme la
    plus probable pour lire les projets à côté d'une autre table."""
    assert _touches_projects_table(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "from app.projects.repository import project_for_user",
        "import app.projects",
        "select * from sections where project_id = %s",
    ],
)
def test_the_guard_does_not_cry_wolf(snippet):
    assert not _touches_projects_table(snippet)


def test_no_projects_query_outside_repository():
    """Le cloisonnement ne vaut que si personne ne contourne le dépôt. Ce test
    casse dès qu'un autre fichier écrit son propre SQL sur la table."""
    root = Path(__file__).resolve().parents[1] / "app"
    allowed = root / "projects" / "repository.py"
    offenders = [
        f for f in root.rglob("*.py")
        if f != allowed and _touches_projects_table(f.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"SQL sur projects hors du dépôt : {offenders}"
