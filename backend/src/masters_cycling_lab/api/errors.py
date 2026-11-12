import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from masters_cycling_lab.application.errors import (
    Conflict,
    GenerationFailed,
    NotFound,
    ProviderUnavailable,
    ServiceError,
    UnsupportedFile,
    UploadTooLarge,
)

log = logging.getLogger(__name__)

SERVICE_ERROR_STATUS: dict[type[ServiceError], int] = {
    NotFound: 404,
    Conflict: 409,
    UploadTooLarge: 413,
    UnsupportedFile: 415,
    GenerationFailed: 502,
    ProviderUnavailable: 503,
}

HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


class ApiError(Exception):
    """Raise from a route to send the error envelope with a specific status and code."""

    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None
    details: dict[str, Any]


class ErrorResponse(BaseModel):
    """Every non-2xx response from /api/v1 has this shape."""

    error: ErrorBody


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = ErrorResponse(error=ErrorBody(code=code, message=message, request_id=request_id, details=details or {}))
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(body.model_dump(), status_code=status_code, headers=response_headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(ServiceError)
    async def handle_service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return error_response(request, SERVICE_ERROR_STATUS.get(type(exc), 400), exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        # Keep headers such as Allow on 405 responses.
        return error_response(request, exc.status_code, code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Leave out the rejected input values: they can contain a whole question or document text.
        errors = [{"location": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return error_response(request, 422, "VALIDATION_ERROR", "The request is not valid.", {"errors": errors})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(request, 500, "INTERNAL_ERROR", "Something went wrong on the server.")
