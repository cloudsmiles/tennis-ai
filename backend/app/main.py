from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import progress, results, session, sources, upload


def create_app() -> FastAPI:
    app = FastAPI(title="tennis-ai")

    # 开发期前端 (vite) 直连后端
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(upload.router)
    app.include_router(sources.router)
    app.include_router(progress.router)
    app.include_router(results.router)
    app.include_router(session.router)

    # 注意：浏览器会话是懒启动的（首次 LLM/登录调用才拉起），
    # 不注册任何启动钩子。
    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


app = create_app()
