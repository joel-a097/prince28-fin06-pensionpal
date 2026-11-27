from pensionpal.api.deps import get_retriever, get_usage_repo
from pensionpal.llm.gateway import FakeLLM, LLMError, LLMGateway


class FakeUsage:
    async def by_day(self, days):
        assert days == 7
        return [
            {
                "date": "2026-11-25",
                "calls": 3,
                "errors": 1,
                "fallbacks": 1,
                "tokens_in": 20,
                "tokens_out": 8,
                "cost_inr": 0.15,
            }
        ]


def test_chat_streams_answer_and_done_metadata(client):
    response = client.post("/v1/chat", json={"message": "How do I transfer PF?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"delta": "A "' in response.text
    assert '"delta": "fake "' in response.text
    assert '"delta": "answer. "' in response.text
    assert "event: done" in response.text
    assert '"provider": "gemini"' in response.text


def test_chat_nonstream_returns_json(client):
    response = client.post(
        "/v1/chat", json={"message": "How do I transfer PF?", "stream": False}
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "A fake answer."
    assert response.json()["model"] == "test-model"


def test_chat_includes_document_citations(client):
    from tests.unit.conftest import FakeRetriever

    citation = {
        "reference": "D1",
        "document_id": "a" * 64,
        "title": "Transfer guide",
        "source_url": "https://example.test/transfer.pdf",
        "page_no": 2,
        "headings": ["Transfer"],
    }

    class Evidence:
        def __init__(self):
            self.reference = "D1"
            self.title = "Transfer guide"
            self.page_no = 2
            self.headings = ["Transfer"]
            self.text = "Members can transfer their PF balance."

        def citation(self):
            return citation

    client.app.dependency_overrides[get_retriever] = lambda: FakeRetriever([Evidence()])
    response = client.post(
        "/v1/chat",
        json={"message": "How do I transfer PF?", "stream": False},
    )

    assert response.status_code == 200
    assert response.json()["citations"] == [citation]


def test_chat_rejects_empty_and_oversized_messages(client):
    assert client.post("/v1/chat", json={"message": ""}).status_code == 422
    assert client.post("/v1/chat", json={"message": "x" * 4001}).status_code == 422


def test_chat_returns_503_when_no_provider_can_answer(client):
    from pensionpal.api.deps import get_gateway

    client.app.dependency_overrides[get_gateway] = lambda: LLMGateway([])
    response = client.post("/v1/chat", json={"message": "question"})
    assert response.status_code == 503
    assert "No model could answer" in response.json()["detail"]


def test_chat_reports_stream_error_after_partial_answer(client):
    from pensionpal.api.deps import get_gateway

    primary = FakeLLM(
        "gemini", script=[("partial", LLMError("cut off", retryable=True))]
    )
    client.app.dependency_overrides[get_gateway] = lambda: LLMGateway([primary])
    response = client.post("/v1/chat", json={"message": "question"})
    assert response.status_code == 200
    assert "Half " in response.text and "event: error" in response.text


def test_usage_summarizes_calls_and_rupees(client):
    client.app.dependency_overrides[get_usage_repo] = lambda: FakeUsage()
    response = client.get("/v1/usage")
    assert response.status_code == 200
    assert response.json()["calls"] == 3
    assert response.json()["errors"] == 1
    assert response.json()["fallbacks"] == 1
    assert response.json()["total_cost_inr"] == 0.15


def test_usage_limits_days_parameter(client):
    assert client.get("/v1/usage?days=0").status_code == 422
    assert client.get("/v1/usage?days=91").status_code == 422


def test_system_prompt_has_safety_lines(client):
    response = client.post("/v1/chat", json={"message": "question", "stream": False})
    assert response.status_code == 200
    system_prompt = " ".join(client.app.state.system_prompt.split())
    assert "could not find enough information" in system_prompt
    assert "Never invent a citation" in system_prompt
