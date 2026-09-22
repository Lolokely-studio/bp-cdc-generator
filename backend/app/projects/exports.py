from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import active_user
from app.core.db import connection
from app.export import storage
from app.export.service import (
    ExportAlreadyRunning,
    is_exporting,
    last_outcome,
    start_export,
)
from app.projects.repository import exports_of_project
from app.projects.routes import _owned

router = APIRouter(prefix="/projects", tags=["exports"])


@router.post("/{project_id}/exports", status_code=status.HTTP_202_ACCEPTED)
async def launch(project_id: UUID, user=Depends(active_user)):
    """Lance le rendu en tâche de fond : Gotenberg peut mettre une minute à
    se réveiller, et une requête HTTP n'a pas à l'attendre."""
    project = await _owned(project_id, user)
    try:
        start_export(project)
    except ExportAlreadyRunning:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            {"code": "export_deja_en_cours"}) from None
    return {"export": "en_cours"}


@router.get("/{project_id}/exports")
async def listing(project_id: UUID, user=Depends(active_user)):
    """Les fichiers déposés, chacun avec un lien signé frais. Le lien est
    produit à chaque lecture et jamais stocké : il expire."""
    await _owned(project_id, user)
    async with connection() as conn:
        rows = await exports_of_project(conn, project_id)
    files = []
    for row in rows:
        files.append({
            "document": row["document"],
            "format": row["format"],
            "brouillon": row["brouillon"],
            "fidele": row["fidele"],
            "lien": await storage.signed_url(row["storage_path"]),
            "cree_le": row["created_at"].isoformat(),
        })
    return {
        "en_cours": is_exporting(str(project_id)),
        "fichiers": files,
        "dernier_export": last_outcome(str(project_id)),
    }
