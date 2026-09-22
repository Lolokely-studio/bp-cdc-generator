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
# --workers 1, figé : le bus d'événements et le registre des runs vivent en
# mémoire du processus (§9.2, une seule instance). `--workers` prend sinon
# par défaut $WEB_CONCURRENCY, que Render fixe d'après le nombre de
# processeurs — passer à un plan plus grand démarrerait alors deux workers,
# chacun croyant être seul à piloter les runs, sans que rien ne le dise.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
