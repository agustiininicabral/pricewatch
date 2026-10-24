from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.database.session import SessionLocal
from app.scheduler.service import UpdateCoordinator

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src"


def create_app(
    *,
    update_coordinator: UpdateCoordinator | None = None,
    start_scheduler: bool = True,
) -> FastAPI:
    coordinator = update_coordinator or UpdateCoordinator(SessionLocal)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        if start_scheduler:
            coordinator.start()
        try:
            yield
        finally:
            coordinator.stop()

    application = FastAPI(
        title="PriceWatch API",
        description=(
            "API local para productos, observaciones, historial y actualizaciones. "
            "Las tiendas sin integración autorizada no reciben consultas."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.update_coordinator = coordinator
    application.include_router(router)
    application.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIR),
        name="frontend-assets",
    )

    @application.get("/", include_in_schema=False)
    def frontend() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    import os

    port = int(os.getenv("PRICEWATCH_PORT", "8000"))
    if not 1 <= port <= 65_535:
        raise ValueError("PRICEWATCH_PORT debe estar entre 1 y 65535.")
    uvicorn.run(app, host="127.0.0.1", port=port)
