FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Le manifeste et le verrou d'abord : tant qu'ils ne bougent pas, la couche
# des dépendances reste en cache et la construction ne coûte presque rien.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
# `--proxy-headers` fait lire X-Forwarded-For à uvicorn, sans quoi
# `request.client.host` vaut l'adresse du routeur de l'hébergeur pour toutes
# les requêtes et la limitation de débit devient un compteur unique partagé
# par tous les utilisateurs. `--forwarded-allow-ips` vaut `*` parce que le
# service n'est joignable qu'à travers ce routeur.
CMD ["sh", "-c", "alembic upgrade head && uvicorn esquisse.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
