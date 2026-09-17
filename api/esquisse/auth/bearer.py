def bearer_token(authorization: str) -> str:
    """Extrait le jeton d'un en-tête Authorization, ou rend une chaîne vide.

    Le schéma est insensible à la casse d'après la norme HTTP. Le comparer au
    caractère près ferait qu'un client envoyant « bearer » se verrait refuser
    l'accès sans raison visible — ou, à la déconnexion, recevrait un 204 sans
    que sa session soit révoquée : il se croirait déconnecté alors que son
    jeton reste valable."""
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""
