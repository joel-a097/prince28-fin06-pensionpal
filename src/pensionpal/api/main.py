"""FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from pensionpal.api.errors import not_found_handler, validation_error_handler
from pensionpal.api.middleware import RequestIDMiddleware
from pensionpal.api.routes.chat import router as chat_router
from pensionpal.api.routes.documents import router as documents_router
from pensionpal.api.routes.health import router as health_router
from pensionpal.api.routes.ingest import router as ingest_router
from pensionpal.config import Settings, get_settings
from pensionpal.db.llm_calls import make_recorder
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.llm.embeddings import GeminiEmbedder
from pensionpal.llm.gateway import build_gateway
from pensionpal.services.retrieval import DocumentRetriever
from pensionpal.workers.queue import IngestQueue


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(cfg)
        app.state.engine = engine
        app.state.session_factory = make_sessionmaker(engine)
        app.state.system_prompt = (
            (cfg.prompts_dir / "chat_system_v1.md").read_text(encoding="utf-8").strip()
        )
        app.state.gateway = build_gateway(
            cfg, recorder=make_recorder(app.state.session_factory)
        )
        app.state.embedder = GeminiEmbedder(
            cfg.gemini_api_key,
            model=cfg.embedding_model,
            batch_size=cfg.embedding_batch_size,
        )
        app.state.retriever = DocumentRetriever(
            app.state.session_factory,
            app.state.embedder,
            limit=cfg.retrieval_limit,
            max_distance=cfg.retrieval_max_distance,
        )
        app.state.ingest_queue = IngestQueue(cfg.redis_url)
        app.state.worker_task = None
        if cfg.worker_in_api:
            from arq.worker import Worker

            from pensionpal.workers.main import WorkerSettings

            worker = Worker(
                functions=WorkerSettings.functions,
                redis_settings=WorkerSettings.redis_settings,
                queue_name=WorkerSettings.queue_name,
                max_jobs=cfg.ingest_concurrency,
                job_timeout=cfg.ingest_job_timeout,
                max_tries=cfg.ingest_max_tries,
                keep_result=0,
                on_startup=WorkerSettings.on_startup,
                on_shutdown=WorkerSettings.on_shutdown,
                ctx={"settings": cfg},
            )
            app.state.worker_task = asyncio.create_task(worker.async_run())
        yield
        if app.state.worker_task:
            app.state.worker_task.cancel()
            await asyncio.gather(app.state.worker_task, return_exceptions=True)
        await app.state.embedder.aclose()
        await app.state.gateway.aclose()
        await engine.dispose()

    app = FastAPI(
        title=cfg.app_name,
        description="EPF and pension assistance API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = cfg

    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(404, not_found_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(chat_router, prefix="/v1")
    app.include_router(ingest_router, prefix="/v1")

    return app
