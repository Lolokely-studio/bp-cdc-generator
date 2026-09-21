from uuid import UUID


class ProjectNotFound(Exception):
    """Levée aussi bien quand le projet n'existe pas que quand il
    appartient à quelqu'un d'autre. Les deux cas se répondent pareil."""


async def create_project(
    conn,
    user_id: UUID,
    *,
    nom: str,
    documents: str,
    profil_cdc: str | None,
    profil_bp: str | None,
    thread_id: str,
    templates_version: str,
) -> UUID:
    """Les six derniers paramètres sont nommés obligatoirement.

    Ce sont des chaînes voisines, interchangeables pour le typage : intervertir
    `profil_cdc` et `profil_bp`, ou `nom` et `documents`, donnerait un appel
    parfaitement valide qui écrirait les valeurs dans les mauvaises colonnes.
    Aucun test ne le verrait, puisqu'un test écrit avec la même interversion
    passerait aussi. L'étoile transforme cette corruption silencieuse en
    `TypeError` au point d'appel."""
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
        row = await cur.fetchone()
        if not row:
            raise ProjectNotFound
        # Les noms de colonnes viennent du curseur, jamais d'une liste tenue à
        # la main en parallèle du SELECT : deux listes finissent par diverger,
        # et `zip` ne dit rien — il tronque en silence ou attache les valeurs
        # aux mauvaises clés.
        columns = [column.name for column in cur.description]
    return dict(zip(columns, row))


RUN_STATUSES = ("idle", "running", "waiting", "failed", "done")


async def set_run_status(conn, project_id: UUID, status: str) -> None:
    """Le seul chemin d'écriture de `run_status`.

    Le contrôle sur `RUN_STATUSES` est ici et non à l'appelant : la colonne
    est du texte libre côté base, et une faute de frappe y passerait sans
    bruit pour ne se voir qu'à l'affichage, des heures plus tard.

    `updated_at` suit : l'index de la liste du propriétaire trie dessus, et
    un projet qui avance sans remonter dans la liste serait déroutant.
    """
    if status not in RUN_STATUSES:
        raise ValueError(f"statut de run inconnu : {status}")
    async with conn.cursor() as cur:
        await cur.execute(
            "update projects set run_status = %s, updated_at = now() where id = %s",
            (status, project_id),
        )
