import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(mot_de_passe: str) -> str:
    return _hasher.hash(mot_de_passe)


def verify_password(mot_de_passe: str, stored_hash: str) -> bool:
    try:
        return _hasher.verify(stored_hash, mot_de_passe)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token() -> tuple[str, bytes]:
    """Rend le jeton en clair, à donner une seule fois au client, et son
    empreinte, seule chose écrite en base. Une fuite de la table sessions
    ne permet pas de se connecter."""
    clair = secrets.token_urlsafe(32)
    return clair, token_hash(clair)


def token_hash(jeton: str) -> bytes:
    return hashlib.sha256(jeton.encode()).digest()
