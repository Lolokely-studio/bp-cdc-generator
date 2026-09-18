from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.db import pool
from app.llm.transport import close_clients


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ouvre le pool au démarrage, le referme à l'arrêt.

    C'est aussi le point d'accroche que réclamera la purge des points de reprise
    du §9.3 de la spec."""
    connection_pool = pool()
    await connection_pool.open(wait=True)
    try:
        yield
    finally:
        await close_clients()
        await connection_pool.close()


def create_app() -> FastAPI:
    """Construit l'application. Une fonction et non un module-niveau :
    les tests en créent une par cas, sans état partagé."""
    app = FastAPI(title="Esquisse", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Sonde de réveil. L'hébergement gratuit s'endort après quinze
        minutes ; l'interface appelle cette route et affiche un écran
        d'attente le temps du redémarrage."""
        return {"statut": "ok"}

    from app.auth.routes import router as auth_router
    app.include_router(auth_router)

    from app.auth.routes import me_router
    app.include_router(me_router)

    return app


app = create_app()
