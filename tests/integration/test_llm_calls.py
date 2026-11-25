from pensionpal.db.llm_calls import LlmCallRepository
from pensionpal.db.session import make_engine, make_sessionmaker


async def test_usage_call_is_saved_and_rolled_up(settings):
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    async with sessions() as session, session.begin():
        repo = LlmCallRepository(session)
        await repo.record(
            {
                "request_id": "integration-request",
                "provider": "gemini",
                "model": "test-model",
                "purpose": "chat",
                "prompt_version": "chat_system_v1",
                "status": "ok",
                "tokens_in": 10,
                "tokens_out": 4,
                "latency_ms": 125,
                "cost_inr": 0.001234,
                "fallback_used": False,
            }
        )
        rows = await repo.by_day(1)
    await engine.dispose()
    assert rows
    assert rows[0]["calls"] == 1
    assert rows[0]["tokens_in"] == 10
    assert rows[0]["cost_inr"] == 0.001234
