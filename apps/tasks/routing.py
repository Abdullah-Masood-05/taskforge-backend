"""
WebSocket URL routing for the tasks app.

Imported by config/asgi.py and exposed via apps/core/routing.py.

Pattern: ws/projects/<uuid:project_id>/board/
The UUID identifies the project whose Kanban board is being viewed.
"""
from django.urls import re_path

from .consumers import ProjectBoardConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/projects/(?P<project_id>[0-9a-f-]{36})/board/$",
        ProjectBoardConsumer.as_asgi(),
    ),
]
