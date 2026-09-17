import anyio
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from esquisse.auth import repository
from esquisse.config import settings
from esquisse.db import connection
from esquisse.security import hash_password, new_token, token_hash, verify_password

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


class LoginRequest(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(max_length=128)


class LoginResponse(BaseModel):
    jeton: str


@router.post("/login")
async def login(demande: LoginRequest) -> LoginResponse:
    async with connection() as conn:
        user = await repository.user_by_email(conn, demande.email)

    # Hors de la connexion et hors de la boucle d'événements, pour la même
    # raison qu'à l'inscription. `verify_password` rend False sur une empreinte
    # absente : on le fait donc tourner même quand l'utilisateur est
    # introuvable, de sorte que les deux cas coûtent le même temps et qu'on
    # ne révèle pas quels comptes existent.
    stored = user["password_hash"] if user else None
    valide = await anyio.to_thread.run_sync(
        verify_password, demande.mot_de_passe, stored
    )
    if not user or not valide:
        raise HTTPException(status_code=401, detail="identifiants_invalides")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="compte_inactif")

    plaintext, token_digest = new_token()
    async with connection() as conn:
        await repository.open_session(
            conn, user["id"], token_digest, settings().session_ttl_hours
        )
    return LoginResponse(jeton=plaintext)


@router.post("/logout", status_code=204)
async def logout(authorization: str = Header(default="")) -> None:
    jeton = authorization.removeprefix("Bearer ").strip()
    if jeton:
        async with connection() as conn:
            await repository.revoke_session(conn, token_hash(jeton))
