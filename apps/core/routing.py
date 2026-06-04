"""
Top-level WebSocket URL patterns.
Delegates to apps.tasks.routing so the tasks app owns its own WS routes.
"""
from apps.tasks.routing import websocket_urlpatterns  # noqa: F401
