from fastapi import APIRouter, Depends

from app.agent.templates import DocumentTemplate, load_catalogue
from app.auth.dependencies import active_user

router = APIRouter(tags=["catalogue"])


def _document(template: DocumentTemplate) -> dict:
    return {
        "profils": dict(template.profils_disponibles),
        "sections": [
            {"id": s.id, "titre": s.titre, "ordre_lecture": s.ordre_lecture,
             "profils": list(s.profils), "validation": s.validation}
            for s in template.sections
        ],
    }


@router.get("/catalogue")
async def catalogue(user=Depends(active_user)) -> dict:
    """Ce que l'écran affiche du catalogue : titres, profils, et la forme de
    chaque fait — son libellé, son type, ses options.

    Jamais les consignes, les grilles ni les objectifs : ce sont des prompts,
    pas du contenu, et rien à l'écran n'en a besoin. Derrière une session,
    comme toute route hors `/auth` (§6).
    """
    cat = load_catalogue()
    return {
        "documents": {"cdc": _document(cat.cdc), "bp": _document(cat.bp)},
        "faits": {
            fact.id: {"libelle": fact.libelle, "type": fact.type, "unite": fact.unite,
                      "options": list(fact.options), "exemple": fact.exemple}
            for fact in cat.facts.values()
        },
    }
