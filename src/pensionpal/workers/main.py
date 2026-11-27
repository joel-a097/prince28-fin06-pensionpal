"""ARQ worker process configuration and lifecycle."""

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

import httpx
from arq.connections import RedisSettings
from sqlalchemy import func, select, update

from pensionpal.config import get_settings
from pensionpal.db.llm_calls import make_recorder
from pensionpal.db.models import IngestItem
from pensionpal.db.session import make_engine, make_sessionmaker
from pensionpal.ingest.fetch import make_client
from pensionpal.llm.doc_meta import DocMeta
from pensionpal.llm.gateway import build_gateway
from pensionpal.llm.prompts import latest
from pensionpal.workers.ingest import Pace, PacedGateway, ingest_document

logger = logging.getLogger("pensionpal.worker")
settings = get_settings()


def make_worker_http_client(concurrency: int) -> httpx.AsyncClient:
    """Use the downloader's polite headers and bound connections to worker jobs."""
    return make_client(max_concurrency=max(1, concurrency))


async def startup(ctx: dict) -> None:
    cfg = ctx["settings"]
    if sys.platform == "win32":
        tess = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR"
        if (tess / "tesseract.exe").is_file():
            os.environ["PATH"] = f"{tess}{os.pathsep}{os.environ.get('PATH', '')}"
    engine = make_engine(cfg)
    ctx["engine"] = engine
    ctx["sessionmaker"] = make_sessionmaker(engine)
    ctx["http"] = make_worker_http_client(cfg.ingest_concurrency)
    ctx["pace"] = Pace(cfg.ingest_rpm)
    ctx["gateway"] = build_gateway(cfg, recorder=make_recorder(ctx["sessionmaker"]))
    ctx["paced_gateway"] = PacedGateway(ctx["gateway"], ctx["pace"])
    ctx["extract"] = None
    if cfg.ingest_extract_enabled and (cfg.gemini_api_key or cfg.groq_api_key):
        version, prompt = latest(cfg.prompts_dir, "extract")
        ctx["extract"] = {
            "schema": DocMeta,
            "prompt": prompt,
            "version": version,
            "chars": 6000,
        }
    async with ctx["sessionmaker"]() as session:
        stale_before = func.now() - timedelta(
            seconds=max(1, cfg.ingest_job_timeout - 5)
        )
        stale = await session.execute(
            update(IngestItem)
            .where(
                IngestItem.status == "running",
                IngestItem.updated_at < stale_before,
                IngestItem.attempts < cfg.ingest_max_tries,
            )
            .values(
                status="queued",
                error="worker stopped before finishing; requeued after lease expiry",
                updated_at=func.now(),
            )
        )
        recovered = stale.rowcount or 0
        await session.execute(
            update(IngestItem)
            .where(
                IngestItem.status == "running",
                IngestItem.updated_at < stale_before,
                IngestItem.attempts >= cfg.ingest_max_tries,
            )
            .values(
                status="failed",
                error="gave up: started maximum times and worker stopped before finishing",
                updated_at=func.now(),
            )
        )
        ids = list(
            await session.scalars(
                select(IngestItem.id).where(IngestItem.status == "queued")
            )
        )
        await session.commit()
    if ids:
        from pensionpal.workers.queue import IngestQueue

        await IngestQueue(cfg.redis_url).put(ids)
    logger.info(
        "worker ready, %s unfinished item(s) put back in the queue (%s stale recovered)",
        len(ids),
        recovered,
    )


async def shutdown(ctx: dict) -> None:
    await ctx["http"].aclose()
    await ctx["gateway"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions: ClassVar[list] = [ingest_document]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = "pensionpal:ingest"
    max_jobs = settings.ingest_concurrency
    job_timeout = settings.ingest_job_timeout
    max_tries = settings.ingest_max_tries
    keep_result = 0
    on_startup = startup
    on_shutdown = shutdown
    ctx: ClassVar[dict] = {"settings": settings}
