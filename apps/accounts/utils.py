"""
Utility functions for the accounts app.
"""
from django.http import JsonResponse


def axes_lockout_response(request, credentials, *args, **kwargs):
    """
    Custom response when django-axes locks out a user.
    Returns JSON instead of the default HTML page.
    """
    return JsonResponse(
        {
            "detail": (
                "Too many failed login attempts. "
                "Your account has been temporarily locked. "
                "Please try again in 30 minutes."
            ),
            "code": "account_locked",
        },
        status=429,
    )
