from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.exceptions import RequestValidationError

from pensionpal.api.errors import (
    not_found_handler,
    validation_error_handler,
)
from pensionpal.api.middleware import RequestIDMiddleware
from pensionpal.core.config import settings
from pensionpal.services.records import get_all_records


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="EPF and pension assistance API",
        version="0.1.0",
    )

    app.add_middleware(RequestIDMiddleware)

    app.add_exception_handler(404, not_found_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/health")
    def health_check():
        return {"status": "healthy", "application": "PensionPal"}

    @app.get("/ready")
    def readiness_check():
        return {"status": "ready", "application": "PensionPal"}

    @app.get("/v1/documents")
    def list_documents(doc_type: str | None = Query(default=None)):
        records = get_all_records()
        if doc_type is not None:
            records = [r for r in records if r.doc_type.lower() == doc_type.lower()]
        return records

    @app.get("/v1/documents/{record_id}")
    def get_document(
        record_id: str = Path(min_length=5, max_length=64),
    ):
        records = get_all_records()
        for record in records:
            if record.id == record_id:
                return record
        raise HTTPException(status_code=404, detail="EPFO document not found")

    @app.get("/v1/stats")
    def get_stats():
        records = get_all_records()
        type_counts: dict[str, int] = {}
        for record in records:
            type_counts[record.doc_type] = type_counts.get(record.doc_type, 0) + 1
        return {
            "total": len(records),
            "by_doc_type": type_counts,
        }

    return app
