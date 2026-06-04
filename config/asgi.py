"""
ASGI config for taskforge project.
Supports both HTTP (via Django) and WebSocket (via Channels) connections.

WebSocket auth: JWT from query-string (?token=<access_jwt>).
See apps/tasks/middleware.py for the design tradeoff discussion.
"""
import os
import django
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.tasks.middleware import JWTAuthMiddlewareStack  # noqa: E402
from apps.core.routing import websocket_urlpatterns       # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        ),
    }
)
