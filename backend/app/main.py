from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="tennis-ai")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
