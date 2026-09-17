from fastapi import FastAPI


def create_app() -> FastAPI:
    """Construit l'application. Une fonction et non un module-niveau :
    les tests en créent une par cas, sans état partagé."""
    app = FastAPI(title="Esquisse", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Sonde de réveil. L'hébergement gratuit s'endort après quinze
        minutes ; l'interface appelle cette route et affiche un écran
        d'attente le temps du redémarrage."""
        return {"statut": "ok"}

    from esquisse.auth.routes import router as auth_router
    app.include_router(auth_router)

    from esquisse.auth.routes import me_router
    app.include_router(me_router)

    return app


app = create_app()
