"""Small ARQ adapter: Redis access is kept out of API and worker logic."""

from uuid import uuid4

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


class IngestQueue:
    def __init__(self, redis_url: str, queue_name: str = "pensionpal:ingest") -> None:
        self.redis_url = redis_url
        self.queue_name = queue_name

    async def put(self, item_ids: list[int]) -> None:
        pool: ArqRedis = await create_pool(RedisSettings.from_dsn(self.redis_url))
        try:
            for item_id in item_ids:
                await pool.enqueue_job(
                    "ingest_document",
                    item_id,
                    _queue_name=self.queue_name,
                    _job_id=f"ingest-{item_id}-{uuid4().hex}",
                )
        finally:
            await pool.aclose()
