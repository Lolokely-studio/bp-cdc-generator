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
                   thread_id, run_status, templates_version,
                   created_at, updated_at
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


async def projects_of_user(conn, user_id: UUID) -> list[dict]:
    """La liste du propriétaire, la plus récemment modifiée d'abord.

    Le tri suit l'index `(user_id, updated_at desc)` posé par la migration
    0002 : sans lui, cette requête ferait un balayage complet dès que la
    table grossirait.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select id, nom, documents, profil_cdc, profil_bp,
                   run_status, created_at, updated_at
            from projects where user_id = %s order by updated_at desc
            """,
            (user_id,),
        )
        # Même motif que `project_for_user` : le curseur rend des tuples, pas
        # des dicts (aucun `row_factory` n'est configuré), donc les colonnes
        # viennent de `cur.description` et non d'une liste tenue à la main.
        columns = [column.name for column in cur.description]
        return [dict(zip(columns, row)) for row in await cur.fetchall()]


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


async def running_projects(conn) -> list[dict]:
    """Les projets que la base croit en cours, tous propriétaires confondus.

    L'exception à la règle « toujours filtrer sur le propriétaire » : cette
    requête sert la réconciliation du démarrage, qui n'agit au nom de
    personne. Elle ne rend que l'identifiant et le fil — de quoi réconcilier,
    rien de plus — pour qu'un appel de trop ne devienne pas une fuite.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, thread_id from projects where run_status = 'running'")
        rows = await cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]


async def finished_projects(conn) -> list[dict]:
    """Les projets que la base croit terminés, tous propriétaires confondus.

    Même exception que `running_projects` à la règle du filtre sur le
    propriétaire : sert la purge de filet du démarrage (§9.3), qui n'agit
    pas plus au nom de quelqu'un.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "select id, thread_id from projects where run_status = 'done'")
        rows = await cur.fetchall()
        columns = [column.name for column in cur.description]
    return [dict(zip(columns, row)) for row in rows]


async def fail_if_still_running(conn, project_id: UUID) -> bool:
    """Passe une ligne `running` à `failed`, mais seulement si elle est
    TOUJOURS `running` au moment de l'écriture (`where run_status =
    'running'`), et rend si l'écriture a eu lieu.

    Sert la réconciliation du démarrage, qui lit `running_projects` puis
    écrit sans rien qui les synchronise : un run peut atteindre `waiting`
    entre les deux. Sans cette garde, l'écriture agirait sur une photo
    périmée et écraserait ce statut plus récent — la réconciliation existe
    précisément parce qu'elle tourne sans coordination avec les runs
    vivants, donc cette course est réelle, pas hypothétique.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            update projects set run_status = 'failed', updated_at = now()
            where id = %s and run_status = 'running'
            """,
            (project_id,),
        )
        return cur.rowcount > 0
