from uuid import UUID


class ProjectNotFound(Exception):
    """Levée aussi bien quand le projet n'existe pas que quand il
    appartient à quelqu'un d'autre. Les deux cas se répondent pareil."""


async def create_project(
    conn,
    user_id: UUID,
    nom: str,
    documents: str,
    profil_cdc: str | None,
    profil_bp: str | None,
    thread_id: str,
    templates_version: str,
) -> UUID:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into projects
                (user_id, nom, documents, profil_cdc, profil_bp, thread_id, templates_version)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (user_id, nom, documents, profil_cdc, profil_bp, thread_id, templates_version),
        )
        return (await cur.fetchone())[0]


async def project_for_user(conn, project_id: UUID, user_id: UUID) -> dict:
    """Seul accès en lecture à la table projects dans toute l'application.
    Le filtre sur le propriétaire est dans la requête, pas dans l'appelant :
    on ne peut pas l'oublier."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select id, user_id, nom, documents, profil_cdc, profil_bp,
                   thread_id, run_status, templates_version
            from projects where id = %s and user_id = %s
            """,
            (project_id, user_id),
        )
        ligne = await cur.fetchone()
    if not ligne:
        raise ProjectNotFound
    champs = ("id", "user_id", "nom", "documents", "profil_cdc", "profil_bp",
              "thread_id", "run_status", "templates_version")
    return dict(zip(champs, ligne))
