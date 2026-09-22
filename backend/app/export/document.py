from dataclasses import dataclass, field

from app.agent.state import Block, Placeholder, Table

# Le titre de chaque document, tel qu'il s'imprime en page de garde.
_DOCUMENT_TITLES = {
    "cdc": "Cahier des charges",
    "bp": "Business plan",
}


@dataclass
class ExportSection:
    title: str
    blocks: list[Block]


@dataclass
class ExportDocument:
    """Ce que les deux rendus, Word et HTML, lisent. Rien d'autre.

    Un document neutre, sans mise en forme : c'est ce qui garantit que le Word
    et le PDF de repli disent la même chose, même quand ils ne se ressemblent
    pas.
    """

    document: str
    title: str
    sections: list[ExportSection] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    draft: bool = False


def assemble(document: str, project_name: str, profil: str,
             rows: list[dict], catalogue) -> ExportDocument:
    """Assemble le document à partir des lignes `sections` d'un projet.

    L'ordre est celui de LECTURE (`ordre_lecture`) : le résumé exécutif est
    rédigé en dernier et se lit en premier. Trier sur l'ordre de rédaction le
    mettrait à la fin du document.

    Une section du plan absente des lignes, ou dont le statut n'est pas
    `done`, reste hors du corps et fait du document un brouillon. C'est le cas
    réel d'un export demandé avant la fin de la rédaction.
    """
    template = catalogue.cdc if document == "cdc" else catalogue.bp
    planned = sorted((s for s in template.sections if profil in s.profils),
                     key=lambda s: s.ordre_lecture)
    by_id = {row["section_id"]: row for row in rows
             if row["document"] == document}

    result = ExportDocument(
        document=document,
        title=f"{_DOCUMENT_TITLES[document]} — {project_name}",
    )
    table_number = 0
    seen_missing: set[str] = set()
    for section in planned:
        row = by_id.get(section.id)
        if row is None or row["statut"] != "done":
            result.draft = True
            continue
        blocks: list[Block] = []
        for block in row["blocks"]:
            if isinstance(block, Table):
                # Une copie, jamais l'objet reçu : l'export lit, il n'écrit
                # pas. `number` stocké repart à 1 à chaque section ; on
                # numérote ici dans l'ordre du document.
                table_number += 1
                block = block.model_copy(update={"number": table_number})
            elif isinstance(block, Placeholder) and block.label not in seen_missing:
                seen_missing.add(block.label)
                result.missing.append(block.label)
            blocks.append(block)
        result.sections.append(ExportSection(title=section.titre, blocks=blocks))
    return result
