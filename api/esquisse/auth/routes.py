import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from esquisse.auth import repository
from esquisse.auth.bearer import bearer_token
from esquisse.auth.dependencies import active_user
from esquisse.config import settings
from esquisse.db import connection
from esquisse.rate_limit import SlidingWindowCounter
from esquisse.security import hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix="/auth", tags=["comptes"])
me_router = APIRouter(tags=["comptes"])

_account_limiter = SlidingWindowCounter(maximum=10, window_seconds=900)


def _check_rate_limit(requete: Request) -> None:
    """Limite par adresse d'appelant.

    Attention à une dépendance invisible en local : en production, le service
    est derrière le routeur de l'hébergeur, et `request.client.host` renvoie
    alors l'adresse de ce routeur, identique pour tout le monde. Sans les
    options `--proxy-headers --forwarded-allow-ips` passées à uvicorn
    (voir le conteneur, tâche 11), tous les utilisateurs partageraient donc
    un seul compteur : dix tentatives de n'importe qui bloqueraient tout le
    monde pendant un quart d'heure. Ce serait un déni de service offert.
    """
    ip = requete.client.host if requete.client else "adresse_inconnue"
    if not _account_limiter.allow(ip):
        raise HTTPException(status_code=429, detail="trop_de_tentatives")


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
async def register(requete: Request, demande: RegisterRequest) -> RegisterResponse:
    _check_rate_limit(requete)
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
async def login(requete: Request, demande: LoginRequest) -> LoginResponse:
    _check_rate_limit(requete)
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
    jeton = bearer_token(authorization)
    if jeton:
        async with connection() as conn:
            await repository.revoke_session(conn, token_hash(jeton))


@me_router.get("/me")
async def me(utilisateur: dict = Depends(active_user)) -> dict:
    return {"email": utilisateur["email"], "compte_actif": True}
