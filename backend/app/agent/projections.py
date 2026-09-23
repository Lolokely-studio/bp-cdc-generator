import json
from uuid import UUID

from app.agent.state import Block, Fact, SectionRef, dump_blocks, parse_blocks

# Le cycle de vie d'une section. Écrits tels quels dans `sections.statut`,
# dont la migration 0002 fixe la valeur par défaut à `pending`.
SECTION_STATUSES = ("pending", "writing", "done", "reopened", "skipped")


async def save_facts(conn, project_id: UUID, facts: dict[str, Fact]) -> None:
    """Projette les faits de l'état vers la table `facts`.

    `valeur` est une colonne jsonb : `None` s'y écrit comme le JSON `null`,
    ce qui distingue « l'utilisateur ne sait pas » d'une ligne absente. La
    distinction est tout l'intérêt de la table.
    """
    async with conn.cursor() as cur:
        for fact in facts.values():
            await cur.execute(
                """
                insert into facts (project_id, fact_id, valeur, source, confiance, updated_at)
                values (%s, %s, %s, %s, %s, now())
                on conflict (project_id, fact_id) do update
                set valeur = excluded.valeur,
                    source = excluded.source,
                    confiance = excluded.confiance,
                    updated_at = now()
                """,
                (project_id, fact.fact_id, json.dumps(fact.value), fact.source, fact.confidence),
            )


async def load_facts(conn, project_id: UUID) -> dict[str, Fact]:
    async with conn.cursor() as cur:
        await cur.execute(
            "select fact_id, valeur, source, confiance from facts where project_id = %s",
            (project_id,),
        )
        rows = await cur.fetchall()
    return {
        fact_id: Fact(fact_id=fact_id, value=value, source=source, confidence=confidence)
        for fact_id, value, source, confidence in rows
    }


async def save_section(
    conn,
    project_id: UUID,
    ref: SectionRef,
    *,
    blocks: list[Block],
    statut: str,
    note: int | None,
    revisions: int,
) -> None:
    """Les paramètres après `ref` sont nommés obligatoirement : `statut`,
    `note` et `revisions` sont trois valeurs voisines qu'un appel positionnel
    pourrait intervertir sans qu'aucun typage ne s'en aperçoive."""
    if statut not in SECTION_STATUSES:
        raise ValueError(f"statut de section inconnu : {statut}")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            insert into sections
                (project_id, section_id, document, ordre, statut, contenu, note, revisions)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (project_id, document, section_id) do update
            set ordre = excluded.ordre,
                statut = excluded.statut,
                contenu = excluded.contenu,
                note = excluded.note,
                revisions = excluded.revisions
            """,
            (project_id, ref.section_id, ref.document, ref.order, statut,
             json.dumps(dump_blocks(blocks)), note, revisions),
        )


async def load_sections(conn, project_id: UUID) -> list[dict]:
    """Rend les sections dans l'ordre de production, blocs déjà relus."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            select section_id, document, ordre, statut, contenu, note, revisions,
                   valide_par, valide_le
            from sections where project_id = %s order by ordre
            """,
            (project_id,),
        )
        columns = [column.name for column in cur.description]
        rows = await cur.fetchall()
    sections = []
    for row in rows:
        section = dict(zip(columns, row))
        section["blocks"] = parse_blocks(section.pop("contenu") or [])
        sections.append(section)
    return sections


async def mark_for_reopening(conn, project_id: UUID, qualified_ids: set[str]) -> int:
    """Passe en `reopened` les sections qu'un fait modifié invalide.

    Prend des identifiants qualifiés — `cdc.perimetre` — parce que c'est ce
    que `Catalogue.sections_to_reopen` rend, et filtre aussi sur le document :
    la clé primaire de `sections` ne le porte pas, et s'en remettre au seul
    `section_id` marcherait aujourd'hui par chance.
    """
    if not qualified_ids:
        return 0
    pairs = [tuple(q.split(".", 1)) for q in sorted(qualified_ids)]
    async with conn.cursor() as cur:
        await cur.execute(
            """
            update sections set statut = 'reopened'
            where project_id = %s and (document, section_id) in (
                select d, s from unnest(%s::text[], %s::text[]) as t(d, s)
            )
            """,
            (project_id, [d for d, _ in pairs], [s for _, s in pairs]),
        )
        return cur.rowcount


async def reproject(
    conn,
    project_id: UUID,
    facts: dict[str, Fact],
    sections: list[tuple[SectionRef, list[Block], str, int | None, int]],
) -> None:
    """Réécrit les projections depuis le point de reprise (§4.6).

    Le point de reprise fait foi : on efface et on recopie, sans rien
    fusionner. Fusionner reviendrait à faire survivre une donnée que le
    graphe ne connaît plus, ce qui est exactement la divergence qu'on répare.
    """
    # Une seule transaction : la connexion est en `autocommit`, donc sans ce
    # bloc les effacements et les réécritures seraient validés un par un. Or
    # cette fonction ne tourne qu'en réparation d'une divergence, c'est-à-dire
    # dans les circonstances où une coupure est le plus probable — et une
    # coupure entre les deux moitiés laisserait le projet vide, ni l'ancien
    # état ni le nouveau. Un seul aller-retour de transaction sur une seule
    # connexion : le pooler en mode transaction le supporte.
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute("delete from facts where project_id = %s", (project_id,))
            await cur.execute("delete from sections where project_id = %s", (project_id,))
        await save_facts(conn, project_id, facts)
        for ref, blocks, statut, note, revisions in sections:
            await save_section(conn, project_id, ref, blocks=blocks, statut=statut,
                               note=note, revisions=revisions)
