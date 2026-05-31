"""
URL patterns for the tasks app.

All routes are prefixed with /api/v1/ in config/urls.py.

Route map:
  /projects/                                        — ProjectViewSet
  /projects/{id}/                                   — ProjectViewSet detail
  /projects/{id}/archive/                           — archive action
  /projects/{id}/statuses/                          — TaskStatusViewSet
  /projects/{id}/statuses/{id}/                     — TaskStatusViewSet detail
  /projects/{id}/statuses/reorder/                  — reorder action
  /projects/{id}/labels/                            — LabelViewSet
  /projects/{id}/labels/{id}/                       — LabelViewSet detail
  /projects/{id}/tasks/                             — TaskViewSet
  /projects/{id}/tasks/{id}/                        — TaskViewSet detail
  /projects/{id}/tasks/{id}/move/                   — move action
  /tasks/{id}/subtasks/                             — SubTaskViewSet
  /tasks/{id}/subtasks/{id}/                        — SubTaskViewSet detail
  /tasks/{id}/comments/                             — CommentViewSet
  /tasks/{id}/comments/{id}/                        — CommentViewSet detail
  /tasks/{id}/activity/                             — ActivityLogViewSet
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ActivityLogViewSet,
    CommentViewSet,
    LabelViewSet,
    ProjectViewSet,
    SubTaskViewSet,
    TaskStatusViewSet,
    TaskViewSet,
)

# Top-level project router
project_router = DefaultRouter()
project_router.register(r"projects", ProjectViewSet, basename="project")

urlpatterns = project_router.urls + [
    # ── TaskStatus (nested under project) ────────────────────────────────────
    path(
        "projects/<uuid:project_pk>/statuses/",
        TaskStatusViewSet.as_view({"get": "list", "post": "create"}),
        name="project-statuses-list",
    ),
    path(
        "projects/<uuid:project_pk>/statuses/reorder/",
        TaskStatusViewSet.as_view({"post": "reorder"}),
        name="project-statuses-reorder",
    ),
    path(
        "projects/<uuid:project_pk>/statuses/<uuid:pk>/",
        TaskStatusViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="project-statuses-detail",
    ),

    # ── Labels (nested under project) ─────────────────────────────────────────
    path(
        "projects/<uuid:project_pk>/labels/",
        LabelViewSet.as_view({"get": "list", "post": "create"}),
        name="project-labels-list",
    ),
    path(
        "projects/<uuid:project_pk>/labels/<uuid:pk>/",
        LabelViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="project-labels-detail",
    ),

    # ── Tasks (nested under project) ──────────────────────────────────────────
    path(
        "projects/<uuid:project_pk>/tasks/",
        TaskViewSet.as_view({"get": "list", "post": "create"}),
        name="project-tasks-list",
    ),
    path(
        "projects/<uuid:project_pk>/tasks/<uuid:pk>/",
        TaskViewSet.as_view({
            "get": "retrieve",
            "patch": "partial_update",
            "delete": "destroy",
        }),
        name="project-tasks-detail",
    ),
    path(
        "projects/<uuid:project_pk>/tasks/<uuid:pk>/move/",
        TaskViewSet.as_view({"patch": "move"}),
        name="project-tasks-move",
    ),

    # ── SubTasks (nested under task) ──────────────────────────────────────────
    path(
        "tasks/<uuid:task_pk>/subtasks/",
        SubTaskViewSet.as_view({"get": "list", "post": "create"}),
        name="task-subtasks-list",
    ),
    path(
        "tasks/<uuid:task_pk>/subtasks/<uuid:pk>/",
        SubTaskViewSet.as_view({
            "get": "retrieve",
            "patch": "partial_update",
            "delete": "destroy",
        }),
        name="task-subtasks-detail",
    ),

    # ── Comments (nested under task) ──────────────────────────────────────────
    path(
        "tasks/<uuid:task_pk>/comments/",
        CommentViewSet.as_view({"get": "list", "post": "create"}),
        name="task-comments-list",
    ),
    path(
        "tasks/<uuid:task_pk>/comments/<uuid:pk>/",
        CommentViewSet.as_view({"delete": "destroy"}),
        name="task-comments-detail",
    ),

    # ── Activity log (nested under task) ─────────────────────────────────────
    path(
        "tasks/<uuid:task_pk>/activity/",
        ActivityLogViewSet.as_view({"get": "list"}),
        name="task-activity-list",
    ),
]
