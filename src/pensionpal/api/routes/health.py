"""Health and readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from pensionpal.api.deps import check_db

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "healthy", "application": "PensionPal"}


@router.get("/ready")
async def readiness_check(db_up: Annotated[bool, Depends(check_db)]):
    if db_up:
        return {"status": "ready", "checks": {"database": True}}
    return JSONResponse(
        status_code=503,
        content={"status": "unavailable", "checks": {"database": False}},
    )
