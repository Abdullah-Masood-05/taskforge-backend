"""
Broadcast helpers for task real-time events.

These functions push task events to all WebSocket clients currently
connected to a project board room via the Redis channel layer.

Design notes:
- `broadcast_task_event` is an async function. It is called from
  Django's synchronous signal handlers using `async_to_sync()`.
- Performance tradeoff: calling `async_to_sync(broadcast_task_event)()`
  inside a signal blocks the HTTP request/response cycle while the
  channel layer round-trips to Redis. For high-throughput workloads,
  move the broadcast into a Celery task to decouple the latency
  (future optimization pass).
- The task payload is serialized here (in the signal context) using
  TaskListSerializer. We avoid deep serialization of subtasks/comments
  to keep the broadcast payload lean.
"""
import structlog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = structlog.get_logger(__name__)


async def broadcast_task_event(
    project_id: str,
    event_type: str,
    task_data: dict | None,
    task_id: str,
) -> None:
    """
    Send a task event to all WebSocket clients in the board room.

    Args:
        project_id: UUID string of the project.
        event_type: One of "task.created", "task.updated", "task.deleted".
        task_data:  Serialized task dict (None for delete events).
        task_id:    UUID string of the task (always present for client-side
                    removal on delete events).
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        logger.warning("broadcast_skipped_no_channel_layer", event_type=event_type)
        return

    group_name = f"board_{project_id}"
    try:
        await channel_layer.group_send(
            group_name,
            {
                "type": "task.event",          # maps to consumer.task_event()
                "event_type": event_type,
                "task": task_data,
                "task_id": task_id,
                "project_id": project_id,
            },
        )
        logger.debug(
            "task_event_broadcast",
            group=group_name,
            event_type=event_type,
            task_id=task_id,
        )
    except Exception as exc:
        # Never let a broadcast failure bubble up and break the HTTP response
        logger.error(
            "task_event_broadcast_failed",
            group=group_name,
            event_type=event_type,
            error=str(exc),
        )


def sync_broadcast_task_event(
    project_id: str,
    event_type: str,
    task_data: dict | None,
    task_id: str,
) -> None:
    """
    Synchronous wrapper around broadcast_task_event for use in Django signals.

    Resilient by design: broadcast failures MUST NOT crash the HTTP response.
    Under Daphne/ASGI on Windows, async_to_sync can raise RuntimeError when
    there is already a running event loop in the calling thread. We catch all
    exceptions so the primary DB write still commits cleanly.
    """
    import asyncio

    try:
        # If called from inside a running event loop (e.g. async Django handler),
        # schedule the coroutine on that loop instead of creating a new one.
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                broadcast_task_event(project_id, event_type, task_data, task_id),
                loop,
            )
            return
    except RuntimeError:
        pass

    try:
        async_to_sync(broadcast_task_event)(project_id, event_type, task_data, task_id)
    except Exception as exc:
        logger.error(
            "sync_broadcast_failed",
            event_type=event_type,
            task_id=task_id,
            error=str(exc),
        )
