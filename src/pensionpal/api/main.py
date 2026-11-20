"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from pensionpal.api.errors import not_found_handler, validation_error_handler
from pensionpal.api.middleware import RequestIDMiddleware
from pensionpal.api.routes.documents import router as documents_router
from pensionpal.api.routes.health import router as health_router
from pensionpal.config import Settings, get_settings
from pensionpal.db.session import make_engine, make_sessionmaker


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(cfg)
        app.state.engine = engine
        app.state.session_factory = make_sessionmaker(engine)
        yield
        await engine.dispose()

    app = FastAPI(
        title=cfg.app_name,
        description="EPF and pension assistance API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(404, not_found_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(health_router)
    app.include_router(documents_router)

    return app
