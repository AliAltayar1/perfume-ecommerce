import logging
from typing import Any, List, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException as FastAPIHTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class ErrorDetail(BaseModel):
    field: Optional[str] = Field(None, examples=["email"])
    issue: str = Field(..., examples=["Field required"])
    type: Optional[str] = Field(None, examples=["missing"])


class ErrorBody(BaseModel):
    code: str = Field(..., examples=["VALIDATION_ERROR"])
    message: str = Field(..., examples=["Input validation failed"])
    details: List[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    success: bool = Field(False, examples=[False])
    error: ErrorBody

HTTP_STATUS_CODE_MAP = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    408: "REQUEST_TIMEOUT",
    409: "CONFLICT",
    410: "GONE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: Optional[dict] = None,
) -> JSONResponse:
    """
    Standardized non-2xx error JSON response structure:
    {
      "success": false,
      "error": {
        "code": "<STRING_ERROR_CODE>",
        "message": "<HUMAN_READABLE_MESSAGE>",
        "details": []
      }
    }
    """
    payload = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details if details is not None else [],
        },
    }
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    """
    Registers uniform exception handlers across the application for:
    - HTTP exceptions (Starlette & FastAPI)
    - Request validation errors
    - SQLAlchemy database integrity errors
    - General SQLAlchemy database errors
    - Catch-all unhandled exceptions
    """

    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = HTTP_STATUS_CODE_MAP.get(exc.status_code, f"HTTP_{exc.status_code}")
        headers = getattr(exc, "headers", None)

        if isinstance(exc.detail, dict):
            message = exc.detail.get("message", str(exc.detail))
            details = exc.detail.get("details", [])
            code = exc.detail.get("code", code)
        elif isinstance(exc.detail, list):
            message = "An error occurred."
            details = exc.detail
        else:
            message = str(exc.detail) if exc.detail else "An HTTP error occurred."
            details = []

        return create_error_response(
            status_code=exc.status_code,
            code=code,
            message=message,
            details=details,
            headers=headers,
        )

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(FastAPIHTTPException, http_exception_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = []
        for error in exc.errors():
            loc = error.get("loc", ())
            # Strip top-level transport keys (e.g. 'body') for a clean field path
            field_parts = [str(part) for part in loc if part not in ("body",)]
            field_name = ".".join(field_parts) if field_parts else (str(loc[-1]) if loc else "unknown")

            details.append({
                "field": field_name,
                "issue": error.get("msg", ""),
                "type": error.get("type", ""),
            })

        return create_error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Validation error",
            details=details,
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(
        request: Request, exc: IntegrityError
    ) -> JSONResponse:
        logger.warning(
            "Database integrity error at %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        return create_error_response(
            status_code=status.HTTP_409_CONFLICT,
            code="DATABASE_CONFLICT",
            message=(
                "A database conflict occurred. The resource may already exist or violates a data integrity constraint."
            ),
            details=[],
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.exception(
            "Database error occurred at %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="DATABASE_ERROR",
            message="A database error occurred. Please try again later.",
            details=[],
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled exception occurred at %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred.",
            details=[],
        )
