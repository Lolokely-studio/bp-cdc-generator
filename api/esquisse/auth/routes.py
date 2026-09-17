import anyio
from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from esquisse.auth import repository
from esquisse.db import connection
from esquisse.security import hash_password

router = APIRouter(prefix="/auth", tags=["comptes"])


class RegisterRequest(BaseModel):
    email: EmailStr
    # Le maximum n'est pas cosmétique : sans lui, un client peut envoyer un
    # mot de passe de plusieurs mégaoctets qu'argon2 mettrait très longtemps à
    # hacher. 128 caractères laissent place à n'importe quelle phrase de passe.
    mot_de_passe: str = Field(min_length=10, max_length=128)


class RegisterResponse(BaseModel):
    compte_actif: bool
    message: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(demande: RegisterRequest) -> RegisterResponse:
    # Hachage hors de la boucle d'événements et AVANT d'ouvrir la connexion :
    # argon2 coûte des dizaines de millisecondes, pendant lesquelles il
    # bloquerait tout le serveur et retiendrait une des cinq connexions du pool.
    digest = await anyio.to_thread.run_sync(hash_password, demande.mot_de_passe)
    async with connection() as conn:
        # La valeur de retour est volontairement ignorée, et ne doit jamais
        # être testée dans un chemin de réponse : c'est ce qui garantit qu'une
        # adresse déjà prise réponde exactement comme une inscription réussie.
        await repository.create_user(conn, demande.email, digest)
    return RegisterResponse(
        compte_actif=False,
        message="Compte créé. Il sera utilisable une fois activé.",
    )
