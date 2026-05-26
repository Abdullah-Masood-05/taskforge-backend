"""
ASGI config for taskforge project.
Supports both HTTP (via channels routing) and WebSocket connections.
"""
import os
import django
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

# Import WS URL patterns (will be populated in later phases)
try:
    from apps.core.routing import websocket_urlpatterns
except ImportError:
    websocket_urlpatterns = []

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
