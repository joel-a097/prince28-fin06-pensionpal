from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def not_found_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    detail = "Not Found"
    if isinstance(exc, HTTPException) and exc.detail:
        detail = str(exc.detail)
    return JSONResponse(
        status_code=404,
        content={
            "type": "about:blank",
            "title": "Not Found",
            "status": 404,
            "detail": detail,
        },
    )


async def validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    errors = []
    if isinstance(exc, RequestValidationError):
        errors = jsonable_encoder(exc.errors(), custom_encoder={ValueError: str})
    return JSONResponse(
        status_code=422,
        content={
            "type": "about:blank",
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "Request validation failed",
            "errors": errors,
        },
    )
