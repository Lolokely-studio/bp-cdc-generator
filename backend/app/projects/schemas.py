from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ProjectCreate(BaseModel):
    """Ce que le front envoie pour créer un projet.

    Les profils sont conditionnels : un projet `cdc` n'a pas de profil de
    business plan, et réclamer les deux obligerait le front à inventer une
    valeur. Le validateur croisé dit lequel est requis — sans lui,
    `plan_for` lèverait plus loin, avec un message qui parlerait du
    catalogue et non du formulaire.
    """

    nom: str = Field(min_length=1, max_length=200)
    documents: Literal["cdc", "bp", "both"]
    profil_cdc: Literal["consultation", "cadrage"] | None = None
    profil_bp: Literal["banque", "investisseur"] | None = None
    idee: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def _profiles_match_the_documents(self):
        if self.documents in ("cdc", "both") and self.profil_cdc is None:
            raise ValueError("profil_cdc est requis pour ce choix de documents")
        if self.documents in ("bp", "both") and self.profil_bp is None:
            raise ValueError("profil_bp est requis pour ce choix de documents")
        return self


class ProjectSummary(BaseModel):
    id: UUID
    nom: str
    documents: str
    profil_cdc: str | None
    profil_bp: str | None
    run_status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectState(BaseModel):
    """Tout ce qu'il faut pour peindre l'écran sans réhydrater le graphe.

    `interaction` est `None` quand le run avance : le front affiche alors la
    rédaction en cours, qu'il reçoit par le flux.
    """

    projet: ProjectSummary
    plan: list[dict]
    curseur: int
    faits: dict[str, dict]
    sections: list[dict]
    interaction: dict | None


class AnswerRequest(BaseModel):
    """La réponse à une interaction précise.

    `reponse` n'est pas typée : les cinq interruptions du §4.5 portent des
    charges utiles différentes — un dictionnaire de faits, une décision de
    relecture, une liste d'arbitrages. Les typer ici obligerait à une union
    discriminée qui devrait suivre chaque évolution du graphe, alors que
    c'est le graphe qui valide ce qu'il reçoit.
    """

    interaction_id: str = Field(min_length=1)
    reponse: Any = None
