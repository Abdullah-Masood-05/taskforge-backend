"""
JWT authentication middleware for Django Channels WebSocket connections.

Django Channels uses ASGI scope instead of Django's standard request object,
so we cannot rely on DRF's JWTAuthentication (which inspects request.META).

This middleware reads the JWT access token from the WebSocket handshake
query-string (?token=<access_jwt>) and validates it with SimpleJWT.

Design tradeoff (documented):
  Query-string tokens appear in server logs. A more secure alternative is a
  short-lived "ticket" endpoint (POST /ws-ticket/ → one-use token stored in Redis).
  That approach is better for production but adds complexity; for this project
  the query-string approach is the standard Django Channels pattern and acceptable.

Usage: wrap URLRouter with JWTAuthMiddleware in asgi.py instead of
       AuthMiddlewareStack.
"""
from urllib.parse import parse_qs

import structlog
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = structlog.get_logger(__name__)


@database_sync_to_async
def _get_user_from_token(token_str):
    """
    Validate the JWT access token and return the associated User, or
    AnonymousUser on any validation failure.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()  # noqa: N806
    try:
        token = AccessToken(token_str)
        user_id = token["user_id"]
        return User.objects.get(pk=user_id)
    except (InvalidToken, TokenError, User.DoesNotExist, KeyError) as exc:
        logger.debug("ws_jwt_auth_failed", error=str(exc))
        return AnonymousUser()


class JWTAuthMiddleware:
    """
    ASGI middleware that authenticates WebSocket connections via JWT
    extracted from the query-string (?token=<access_jwt>).

    Sets scope["user"] before passing the connection downstream.
    Unauthenticated connections receive AnonymousUser — the consumer
    is responsible for rejecting them.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            qs = parse_qs(scope.get("query_string", b"").decode("utf-8"))
            token_list = qs.get("token", [])
            if token_list:
                scope["user"] = await _get_user_from_token(token_list[0])
            else:
                scope["user"] = AnonymousUser()

        return await self.inner(scope, receive, send)


def JWTAuthMiddlewareStack(inner):  # noqa: N802
    """Convenience wrapper analogous to AuthMiddlewareStack."""
    return JWTAuthMiddleware(inner)
