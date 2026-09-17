from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field

from esquisse.auth import repository
from esquisse.db import connection
from esquisse.security import hash_password

router = APIRouter(prefix="/auth", tags=["comptes"])


class RegisterRequest(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(min_length=10)


class RegisterResponse(BaseModel):
    compte_actif: bool
    message: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(demande: RegisterRequest) -> RegisterResponse:
    async with connection() as conn:
        await repository.create_user(conn, demande.email, hash_password(demande.mot_de_passe))
    return RegisterResponse(
        compte_actif=False,
        message="Compte créé. Il sera utilisable une fois activé.",
    )
