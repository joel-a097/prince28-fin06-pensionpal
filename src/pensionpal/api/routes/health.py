"""Health and readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from pensionpal.api.deps import check_db

router = APIRouter()


@router.api_route("/health", methods=["GET", "HEAD"])
def health_check(request: Request):
    settings = request.app.state.settings
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "version": settings.git_sha,
    }


@router.get("/ready")
async def readiness_check(db_up: Annotated[bool, Depends(check_db)]):
    if db_up:
        return {"status": "ready", "checks": {"database": True}}
    return JSONResponse(
        status_code=503,
        content={"status": "unavailable", "checks": {"database": False}},
    )
