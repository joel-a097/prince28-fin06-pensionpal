from fastapi.testclient import TestClient

from pensionpal.main import app

client = TestClient(app)


def test_get_all_documents():
    response = client.get("/documents")

    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_get_document_by_id():
    response = client.get("/documents/EPFO-TRANSFER-001")

    assert response.status_code == 200
    assert response.json()["id"] == "EPFO-TRANSFER-001"


def test_get_document_with_invalid_id():
    response = client.get("/documents/WRONG-ID")

    assert response.status_code == 404
    assert response.json() == {"detail": "EPFO document not found"}
