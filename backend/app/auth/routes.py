import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.auth import repository
from app.auth.bearer import bearer_token
from app.auth.dependencies import active_user
from app.core.config import settings
from app.core.db import connection
from app.core.rate_limit import SlidingWindowCounter
from app.core.security import hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix="/auth", tags=["comptes"])
me_router = APIRouter(tags=["comptes"])

_account_limiter = SlidingWindowCounter(maximum=10, window_seconds=900)


def _caller_address(request: Request) -> str:
    """Adresse de l'appelant telle que l'a vue le routeur de l'hébergeur.

    On analyse `X-Forwarded-For` plutôt que de laisser uvicorn le faire : avec
    `--forwarded-allow-ips='*'`, uvicorn retient la PREMIÈRE entrée, qui est
    écrite par l'appelant. N'importe qui pourrait alors choisir sa propre clé
    de limitation et envoyer autant de tentatives qu'il veut.

    Chaque routeur ajoute à la fin l'adresse qu'il a constatée. La dernière
    entrée est donc celle vue par le routeur de l'hébergeur, la seule que
    l'appelant ne contrôle pas."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "adresse_inconnue"


def _check_rate_limit(request: Request) -> None:
    if not _account_limiter.allow(_caller_address(request)):
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
async def register(request: Request, payload: RegisterRequest) -> RegisterResponse:
    _check_rate_limit(request)
    # Hachage hors de la boucle d'événements et AVANT d'ouvrir la connexion :
    # argon2 coûte des dizaines de millisecondes, pendant lesquelles il
    # bloquerait tout le serveur et retiendrait une des cinq connexions du pool.
    digest = await anyio.to_thread.run_sync(hash_password, payload.mot_de_passe)
    async with connection() as conn:
        # La valeur de retour est volontairement ignorée, et ne doit jamais
        # être testée dans un chemin de réponse : c'est ce qui garantit qu'une
        # adresse déjà prise réponde exactement comme une inscription réussie.
        await repository.create_user(conn, payload.email, digest)
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
async def login(request: Request, payload: LoginRequest) -> LoginResponse:
    _check_rate_limit(request)
    async with connection() as conn:
        user = await repository.user_by_email(conn, payload.email)

    # Hors de la connexion et hors de la boucle d'événements, pour la même
    # raison qu'à l'inscription. `verify_password` rend False sur une empreinte
    # absente : on le fait donc tourner même quand l'utilisateur est
    # introuvable, de sorte que les deux cas coûtent le même temps et qu'on
    # ne révèle pas quels comptes existent.
    stored = user["password_hash"] if user else None
    valid = await anyio.to_thread.run_sync(
        verify_password, payload.mot_de_passe, stored
    )
    if not user or not valid:
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
    token = bearer_token(authorization)
    if token:
        async with connection() as conn:
            await repository.revoke_session(conn, token_hash(token))


@me_router.get("/me")
async def me(user: dict = Depends(active_user)) -> dict:
    return {"email": user["email"], "compte_actif": True}
