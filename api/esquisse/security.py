import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_hasher = PasswordHasher()

# Empreinte factice, calculée une fois au chargement du module. Elle sert
# uniquement à payer le coût d'argon2 quand aucune empreinte réelle n'existe.
_DUMMY_HASH = _hasher.hash("empreinte factice pour egaliser le temps de reponse")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str | None, stored_hash: str | None) -> bool:
    """Rend toujours un booléen, jamais une exception.

    Le cas `None` n'est pas théorique : pour ne pas révéler quels comptes
    existent, un appelant vérifie même quand l'utilisateur est introuvable, et
    passe alors une empreinte absente. argon2 lèverait un `AttributeError`
    avant d'atteindre ses propres exceptions, qui remonterait en erreur serveur.

    Mais rendre `False` tout de suite ne suffit pas : le chemin « compte
    inconnu » répondrait en microsecondes là où « mauvais mot de passe » paie
    les dizaines de millisecondes d'argon2, et cet écart révélerait
    précisément ce qu'on cherche à cacher. On vérifie donc contre une
    empreinte factice pour payer le même coût."""
    if not password:
        return False
    target = stored_hash if stored_hash else _DUMMY_HASH
    try:
        valid = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    # Une empreinte absente ne vaut jamais un succès, même dans le cas
    # improbable où le mot de passe correspondrait à l'empreinte factice.
    return valid and stored_hash is not None


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
