"""Persistence and rollups for LLM usage."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pensionpal.db.models import LlmCall


class LlmCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, row: dict[str, Any]) -> None:
        values = dict(row)
        if "cost_inr" in values:
            values["cost_inr"] = Decimal(str(values["cost_inr"])).quantize(
                Decimal("0.000001")
            )
        self.session.add(LlmCall(**values))
        await self.session.flush()

    async def by_day(self, days: int = 7) -> list[dict[str, Any]]:
        since = datetime.combine(
            date.today() - timedelta(days=days - 1), time.min, tzinfo=UTC
        )
        day = func.date(LlmCall.created_at).label("day")
        stmt = (
            select(
                day,
                func.count(LlmCall.id).label("calls"),
                func.count(LlmCall.id)
                .filter(LlmCall.status == "error")
                .label("errors"),
                func.count(LlmCall.id)
                .filter(LlmCall.fallback_used.is_(True))
                .label("fallbacks"),
                func.coalesce(func.sum(LlmCall.tokens_in), 0).label("tokens_in"),
                func.coalesce(func.sum(LlmCall.tokens_out), 0).label("tokens_out"),
                func.coalesce(func.sum(LlmCall.cost_inr), 0).label("cost_inr"),
            )
            .where(LlmCall.created_at >= since)
            .group_by(day)
            .order_by(day.desc())
        )
        results = await self.session.execute(stmt)
        return [
            {
                "date": row.day.isoformat(),
                "calls": row.calls,
                "errors": row.errors,
                "fallbacks": row.fallbacks,
                "tokens_in": row.tokens_in,
                "tokens_out": row.tokens_out,
                "cost_inr": float(row.cost_inr),
            }
            for row in results
        ]


def make_recorder(
    sessions: async_sessionmaker[AsyncSession],
):
    """Return a gateway callback that commits each provider attempt independently."""

    async def record(row: dict[str, Any]) -> None:
        async with sessions() as session, session.begin():
            await LlmCallRepository(session).record(row)

    return record
