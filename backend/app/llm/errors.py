class LlmError(Exception):
    """Racine des erreurs de la couche modèles."""


class ModelUnavailable(LlmError):
    """Ce modèle-là est inutilisable : retiré, inconnu, ou sortie hors schéma.

    L'essai suivant se fait sur le modèle suivant du **même** fournisseur.
    Les paliers gratuits retirent des modèles sans prévenir ; changer de
    fournisseur pour cela abandonnerait les modèles encore valides du
    fournisseur courant.
    """

    def __init__(self, model: str, reason: str) -> None:
        super().__init__(f"modèle {model} inutilisable : {reason}")
        self.model = model
        self.reason = reason


class ProviderUnavailable(LlmError):
    """Le fournisseur entier refuse ou ne répond pas.

    L'essai suivant se fait sur le fournisseur suivant de la route. `issue`
    prend une des valeurs de la colonne `llm_usage.issue` — `quota`,
    `erreur`, `timeout` — et part telle quelle en base.
    """

    def __init__(self, provider: str, issue: str, reason: str) -> None:
        super().__init__(f"fournisseur {provider} indisponible ({issue}) : {reason}")
        self.provider = provider
        self.issue = issue
        self.reason = reason


class NoProviderAvailable(LlmError):
    """La route entière est épuisée.

    Rien n'est perdu : le point de reprise reste intact, le projet passe en
    `run_status = 'failed'` et l'utilisateur voit un bouton « Reprendre »
    (§5.3). `attempts` retient ce qui a été tenté et pourquoi chacun a
    échoué — sans cette liste, un échec de route ne se diagnostique pas.
    """

    def __init__(self, route: str, attempts: list[str]) -> None:
        detail = " ; ".join(attempts) if attempts else "aucun essai possible"
        super().__init__(f"route {route} épuisée après {len(attempts)} essais : {detail}")
        self.route = route
        self.attempts = attempts
