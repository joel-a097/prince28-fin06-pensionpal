from fastapi.testclient import TestClient

from pensionpal.main import app

client = TestClient(app)


def test_list_documents_returns_all():
    response = client.get("/v1/documents")

    assert response.status_code == 200
    records = response.json()
    assert len(records) >= 20


def test_list_documents_has_required_fields():
    response = client.get("/v1/documents")

    assert response.status_code == 200
    record = response.json()[0]
    for field in (
        "id",
        "doc_type",
        "number",
        "date",
        "topic",
        "condition",
        "form",
        "effective_from",
    ):
        assert field in record


def test_get_document_by_id():
    response = client.get("/v1/documents/EPFO-TRANSFER-001")

    assert response.status_code == 200
    assert response.json()["id"] == "EPFO-TRANSFER-001"


def test_get_document_not_found_returns_404():
    response = client.get("/v1/documents/EPFO-DOES-NOT-EXIST")

    assert response.status_code == 404
    body = response.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert "detail" in body


def test_get_document_id_too_short_returns_422():
    response = client.get("/v1/documents/AB")

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == 422
    assert body["title"] == "Unprocessable Entity"


def test_filter_documents_by_doc_type():
    response = client.get("/v1/documents?doc_type=Scheme")

    assert response.status_code == 200
    records = response.json()
    assert len(records) >= 1
    for record in records:
        assert record["doc_type"].lower() == "scheme"


def test_filter_documents_unknown_doc_type_returns_empty():
    response = client.get("/v1/documents?doc_type=NonExistentType")

    assert response.status_code == 200
    assert response.json() == []


def test_stats_endpoint():
    response = client.get("/v1/stats")

    assert response.status_code == 200
    body = response.json()
    assert "total" in body
    assert body["total"] >= 20
    assert "by_doc_type" in body
    assert isinstance(body["by_doc_type"], dict)


def test_request_id_on_documents():
    response = client.get("/v1/documents")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"] != ""
