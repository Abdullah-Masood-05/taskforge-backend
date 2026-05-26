"""
Custom DRF exception handler — standardises all error responses.

Every error from the API will have this shape:
{
    "status": "error",
    "code": "validation_error",
    "message": "Human-readable summary",
    "errors": { ... field-level errors if applicable ... }
}
"""
import structlog
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = structlog.get_logger(__name__)


def custom_exception_handler(exc, context):
    # Let DRF build the initial response
    response = exception_handler(exc, context)

    if response is not None:
        # Normalise into our standard shape
        original_data = response.data

        if isinstance(original_data, dict):
            # Grab a top-level 'detail' if present
            message = original_data.get("detail", str(exc))
            errors = {k: v for k, v in original_data.items() if k != "detail"}
        elif isinstance(original_data, list):
            message = str(exc)
            errors = {"non_field_errors": original_data}
        else:
            message = str(exc)
            errors = {}

        error_code = getattr(exc, "default_code", "error")

        response.data = {
            "status": "error",
            "code": error_code,
            "message": message,
            **({"errors": errors} if errors else {}),
        }

    return response
