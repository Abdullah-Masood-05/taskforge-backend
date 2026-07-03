"""
JWT authentication middleware for Django Channels WebSocket connections.

Design decisions:
- Token is read from the `?token=<jwt>` query parameter because
  browsers cannot send custom headers during the WebSocket handshake.
- This means the JWT appears in the WS URL and potentially in server
  access logs. Acceptable for a portfolio project; for production use
  a short-lived "ticket" endpoint instead.
- On validation failure we set scope["user"] = AnonymousUser() and let
  the consumer's connect() reject the connection with a 403 close code.
- Uses SimpleJWT's UntypedToken for validation (works with any token
  type: access tokens only). We explicitly check the token_type claim
  to reject refresh tokens.
"""
from urllib.parse import parse_qs

from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

User = get_user_model()


async def get_user_from_token(token_key: str):
    """
    Validate a JWT access token and return the corresponding User.

    Returns AnonymousUser if the token is missing, malformed, or expired.
    Runs in async context — uses sync_to_async for ORM access.
    """
    from asgiref.sync import sync_to_async
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from rest_framework_simplejwt.tokens import UntypedToken

    if not token_key:
        return AnonymousUser()

    try:
        # Decode and validate the token (raises on expiry / bad signature)
        untyped = UntypedToken(token_key)

        # Reject refresh tokens — only access tokens are permitted for WS auth
        if untyped.get("token_type") != "access":
            return AnonymousUser()

        user_id = untyped.get("user_id")
        if not user_id:
            return AnonymousUser()

        user = await sync_to_async(User.objects.get)(id=user_id)
        return user

    except (InvalidToken, TokenError, User.DoesNotExist):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    ASGI middleware that authenticates WebSocket connections via JWT.

    Reads the token from `?token=<jwt>` in the WS URL query string and
    populates scope["user"] before the request reaches the consumer.
    The consumer's connect() should close with code 4003 if the user is
    anonymous (not authenticated).
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            query_string = scope.get("query_string", b"").decode("utf-8")
            params = parse_qs(query_string)
            token_list = params.get("token", [])
            token_key = token_list[0] if token_list else ""
            scope["user"] = await get_user_from_token(token_key)

        return await super().__call__(scope, receive, send)
