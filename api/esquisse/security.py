import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str | None, stored_hash: str | None) -> bool:
    """Rend toujours un booléen, jamais une exception.

    Le cas `None` n'est pas théorique : pour ne pas révéler quels comptes
    existent, un appelant peut vouloir vérifier même quand l'utilisateur est
    introuvable, et passe alors une empreinte absente. argon2 lèverait un
    `AttributeError` avant même d'atteindre ses propres exceptions, qui
    remonterait en erreur serveur."""
    if not password or not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token() -> tuple[str, bytes]:
    """Rend le jeton en clair, à donner une seule fois au client, et son
    empreinte, seule chose écrite en base. Une fuite de la table sessions
    ne permet pas de se connecter."""
    plaintext = secrets.token_urlsafe(32)
    return plaintext, token_hash(plaintext)


def token_hash(token: str) -> bytes:
    """SHA-256 nu, sans sel ni étirement, volontairement : le jeton porte déjà
    256 bits d'entropie tirés du générateur du système, donc le ralentir
    n'apporte rien contre la force brute — alors qu'une empreinte
    déterministe permet de retrouver la session par égalité indexée. Le
    contraste avec argon2id sur les mots de passe est un choix, pas un oubli."""
    return hashlib.sha256(token.encode()).digest()
