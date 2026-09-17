from esquisse.security import hash_password, verify_password, new_token, token_hash


def test_hash_does_not_contain_password():
    e = hash_password("correct horse battery staple")
    assert "correct" not in e
    assert e.startswith("$argon2id$")


def test_verify_accepts_correct_password():
    e = hash_password("motdepasse")
    assert verify_password("motdepasse", e) is True


def test_verify_rejects_wrong_password():
    e = hash_password("motdepasse")
    assert verify_password("autrechose", e) is False


def test_same_password_hashes_differ():
    """Le sel rend chaque empreinte unique : deux comptes avec le même
    mot de passe n'ont pas la même ligne en base."""
    assert hash_password("identique") != hash_password("identique")


def test_verify_refuses_none_instead_of_crashing():
    """Un appelant qui normalise le temps de réponse sur « utilisateur
    inconnu » passe naturellement None comme empreinte. Ce module doit
    répondre « non », jamais lever : une exception ici devient une 500."""
    assert verify_password("motdepasse", None) is False
    assert verify_password(None, hash_password("motdepasse")) is False
    assert verify_password("", "") is False


def test_new_token_is_unpredictable_and_digest_stable():
    clair_a, h_a = new_token()
    clair_b, h_b = new_token()
    assert clair_a != clair_b
    assert len(clair_a) >= 43           # 32 octets en base64url
    assert h_a == token_hash(clair_a)
    assert len(h_a) == 32               # SHA-256
