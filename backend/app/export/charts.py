import io
from dataclasses import dataclass

import matplotlib

# Imposé AVANT tout import de pyplot : le serveur n'a pas d'écran, et le
# moteur par défaut chercherait une interface graphique au premier tracé.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402


@dataclass
class Chart:
    title: str
    png: bytes


def _numbers(computation) -> list[float]:
    """Relu depuis le point de reprise, un calcul peut revenir en objet ou
    en dictionnaire selon le sérialiseur : on lit les deux."""
    if isinstance(computation, dict):
        return list(computation.get("numbers") or [])
    return list(getattr(computation, "numbers", None) or [])


def _render(figure) -> bytes:
    buffer = io.BytesIO()
    try:
        figure.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    finally:
        # Fermer la figure n'est pas du ménage : pyplot garde une référence
        # à chacune, et un service qui exporte en boucle finirait par saturer
        # ses 512 Mo. `finally`, parce qu'un échec répété de `savefig` ne doit
        # pas en laisser une ouverte à chaque fois.
        plt.close(figure)
    return buffer.getvalue()


def _income_series(numbers: list[float]) -> tuple[list[float], list[float]] | None:
    """(chiffre d'affaires, résultat) par année, dans l'ordre où
    `income_statement_3y` range ses triplets. `None` si incomplet."""
    if len(numbers) < 9:
        return None
    return ([numbers[i * 3] for i in range(3)],
            [numbers[i * 3 + 2] for i in range(3)])


def _income_chart(numbers: list[float]) -> Chart | None:
    """Trois triplets (chiffre d'affaires, marge brute, résultat) par année,
    dans l'ordre où `income_statement_3y` les range."""
    series = _income_series(numbers)
    if series is None:
        return None
    revenue, result = series
    years = ["Année 1", "Année 2", "Année 3"]
    figure, axis = plt.subplots(figsize=(6, 3.2))
    positions = range(3)
    axis.bar([p - 0.2 for p in positions], revenue, width=0.4,
             label="Chiffre d'affaires")
    axis.bar([p + 0.2 for p in positions], result, width=0.4, label="Résultat")
    axis.set_xticks(list(positions), years)
    axis.axhline(0, linewidth=0.8, color="black")
    axis.legend(frameon=False)
    axis.set_title("Chiffre d'affaires et résultat sur trois ans")
    return Chart("Chiffre d'affaires et résultat sur trois ans", _render(figure))


def _cash_series(numbers: list[float]) -> list[float] | None:
    """Les douze soldes de fin de mois. `None` si incomplet."""
    if len(numbers) < 12:
        return None
    return numbers[:12]


def _cash_chart(numbers: list[float]) -> Chart | None:
    """Les douze soldes de fin de mois, dans l'ordre de `cash_plan_12m`."""
    series = _cash_series(numbers)
    if series is None:
        return None
    figure, axis = plt.subplots(figsize=(6, 3.2))
    axis.plot(range(1, 13), series, marker="o")
    axis.axhline(0, linewidth=0.8, color="black")
    axis.set_xticks(range(1, 13))
    axis.set_xlabel("Mois")
    axis.set_title("Trésorerie de fin de mois")
    return Chart("Trésorerie de fin de mois", _render(figure))


_CHARTS = {
    "compte_resultat_3ans": _income_chart,
    "plan_tresorerie_12mois": _cash_chart,
}


def charts_for(computations: dict) -> list[Chart]:
    """Un graphique par calcul connu et présent, dans un ordre stable.

    Un calcul absent — un fait manquant l'a empêché de tourner — donne un
    document sans ce graphique, jamais un export en échec.
    """
    charts = []
    for name, build in _CHARTS.items():
        if name in computations:
            chart = build(_numbers(computations[name]))
            if chart is not None:
                charts.append(chart)
    return charts
