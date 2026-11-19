from fastapi import FastAPI, HTTPException

from pensionpal.api.middleware import RequestIDMiddleware
from pensionpal.core.config import settings
from pensionpal.core.logging_config import setup_logging
from pensionpal.services.records import get_all_records

setup_logging()

app = FastAPI(
    title=settings.app_name,
    description="EPF and pension assistance API",
    version="0.1.0",
)
app.add_middleware(RequestIDMiddleware)


@app.get("/")
def home():
    return {"message": "Welcome to PensionPal API"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "application": "PensionPal"}


@app.get("/ready")
def readiness_check():
    return {"status": "ready", "application": "PensionPal"}


@app.get("/documents")
def list_documents():
    return get_all_records()


@app.get("/documents/{record_id}")
def get_document(record_id: str):
    records = get_all_records()

    for record in records:
        if record.id == record_id:
            return record

    raise HTTPException(
        status_code=404,
        detail="EPFO document not found",
    )
