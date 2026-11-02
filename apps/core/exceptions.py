"""Consistent API error handling.

Every error returned by the API uses the following shape::

    {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed.",
            "details": {...},          # validation errors only
            "request_id": "..."       # when available
        }
    }

Unhandled exceptions are logged and converted to a generic 500 response so that
stack traces, SQL, secrets and other internals never reach clients.
"""

import logging

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("apps.api")

STATUS_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "authentication_failed",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_406_NOT_ACCEPTABLE: "not_acceptable",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
}

STATUS_MESSAGES = {
    status.HTTP_403_FORBIDDEN: "You do not have permission to perform this action.",
    status.HTTP_404_NOT_FOUND: "Not found.",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed.",
    status.HTTP_406_NOT_ACCEPTABLE: (
        "Could not satisfy the requested content negotiation."
    ),
    status.HTTP_409_CONFLICT: "The request conflicts with the current state.",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Unsupported media type.",
    status.HTTP_429_TOO_MANY_REQUESTS: "Request was throttled. Try again later.",
}


class Conflict(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state."
    default_code = "conflict"


def _detail_message(data, fallback):
    if isinstance(data, dict):
        detail = data.get("detail")
        if detail is not None and not isinstance(detail, (dict, list)):
            return str(detail)
    if isinstance(data, list) and len(data) == 1:
        return str(data[0])
    if isinstance(data, str):
        return data
    return fallback


def _request_id(context):
    request = context.get("request")
    return getattr(request, "request_id", None)


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    request_id = _request_id(context)

    if response is None:
        logger.exception("Unhandled API exception")
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "request_id": request_id,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    status_code = response.status_code
    code = STATUS_CODES.get(status_code, "error")
    message = STATUS_MESSAGES.get(status_code)
    details = None

    if isinstance(exc, exceptions.ValidationError):
        code = "validation_error"
        message = "Request validation failed."
        details = response.data
    elif status_code == status.HTTP_401_UNAUTHORIZED:
        if isinstance(exc, exceptions.NotAuthenticated):
            code = "authentication_required"
            message = "Authentication credentials were not provided."
        else:
            code = "authentication_failed"
            message = _detail_message(response.data, "Authentication failed.")
    elif status_code == status.HTTP_400_BAD_REQUEST:
        message = _detail_message(response.data, "The request could not be processed.")
    elif message is None:
        message = _detail_message(response.data, "The request could not be completed.")

    if status_code >= 500:
        logger.error("API server error: %s", type(exc).__name__)
        code = "server_error"
        message = "An unexpected error occurred."
        details = None

    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    if request_id:
        error["request_id"] = request_id

    response.data = {"error": error}
    return response
