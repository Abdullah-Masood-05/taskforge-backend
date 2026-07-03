"""
WebSocket consumer for real-time Kanban board updates.

Group naming: board_{project_id}

Message types pushed to clients:
  task.created  — a task was created in this project
  task.updated  — a task field was changed (title, priority, status, assignee…)
  task.deleted  — a task was soft-deleted
  task.moved    — a task was dragged to a new column / position

Client → server messages are ignored for MVP (server push only).

Auth: scope["user"] is set by JWTAuthMiddlewareStack before connect().
Unauthenticated or non-member connections are rejected with close code 4001.
"""

import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

logger = structlog.get_logger(__name__)


class ProjectBoardConsumer(AsyncJsonWebsocketConsumer):
    """
    Real-time sync for a single project's Kanban board.

    Each connected browser tab joins group  board_<project_id>.
    Task mutations broadcast to that group via broadcast_task_event().
    """

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self):
        self.project_id = self.scope["url_route"]["kwargs"]["project_id"]
        self.group_name = f"board_{self.project_id}"
        user = self.scope.get("user", AnonymousUser())

        # Reject unauthenticated connections
        if isinstance(user, AnonymousUser) or not user.is_authenticated:
            logger.warning("ws_connect_rejected_unauthenticated", project_id=self.project_id)
            await self.close(code=4001)
            return

        # Verify the user is a member of the org that owns this project
        is_member = await self._is_org_member(user, self.project_id)
        if not is_member:
            logger.warning(
                "ws_connect_rejected_not_member",
                project_id=self.project_id,
                user_id=str(user.pk),
            )
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            "ws_connected",
            project_id=self.project_id,
            user_id=str(user.pk),
            channel=self.channel_name,
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(
            "ws_disconnected",
            project_id=getattr(self, "project_id", "unknown"),
            close_code=close_code,
        )

    async def receive_json(self, content, **kwargs):
        # MVP: server push only — client→server messages are silently dropped.
        # Future: handle optimistic undo, presence pings, cursor positions, etc.
        pass

    # ── Group message handler ──────────────────────────────────────────────────

    async def task_event(self, event):
        """
        Called by the channel layer when broadcast_task_event sends to this group.
        Forwards the payload directly to the WebSocket client.
        """
        await self.send_json({
            "type": event["event_type"],
            "task": event.get("task"),
            "project_id": event.get("project_id"),
            "timestamp": event.get("timestamp"),
        })

    # ── DB helpers ─────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _is_org_member(self, user, project_id):
        """Check that the user is a member of the org that owns the project."""
        from apps.organizations.models import Membership
        from apps.tasks.models import Project

        try:
            project = Project.objects.select_related("organization").get(
                pk=project_id,
                is_deleted=False,
            )
        except Project.DoesNotExist:
            return False

        return Membership.objects.filter(
            user=user,
            organization=project.organization,
        ).exists()
