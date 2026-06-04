"""
ViewSets for the tasks app.

URL structure:
  /projects/                              ProjectViewSet
  /projects/{id}/statuses/               TaskStatusViewSet
  /projects/{id}/statuses/reorder/       reorder action
  /projects/{id}/labels/                 LabelViewSet
  /projects/{id}/tasks/                  TaskViewSet
  /tasks/{id}/move/                      move action (drag-and-drop)
  /tasks/{id}/subtasks/                  SubTaskViewSet
  /tasks/{id}/comments/                  CommentViewSet
  /tasks/{id}/activity/                  ActivityLogViewSet

All querysets are scoped to request.org (set by CurrentOrgMiddleware).
Permission model:
  - Read endpoints:  IsOrgMember
  - Write endpoints: IsOrgMember (members can create/update tasks)
  - Destructive:     IsOrgAdminOrMember (own tasks) or IsOrgAdmin (projects)
"""
import structlog
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsOrgAdmin, IsOrgMember
from apps.core.pagination import CreatedAtCursorPagination
from .filters import ProjectFilter, TaskFilter
from .models import ActivityLog, Comment, Label, Project, SubTask, Task, TaskStatus
from .serializers import (
    ActivityLogSerializer,
    CommentSerializer,
    LabelSerializer,
    ProjectListSerializer,
    ProjectSerializer,
    SubTaskSerializer,
    TaskDetailSerializer,
    TaskListSerializer,
    TaskMoveSerializer,
    TaskStatusReorderSerializer,
    TaskStatusSerializer,
)

logger = structlog.get_logger(__name__)


def _get_project(view, check_archived=False):
    """
    Resolve the project from the URL kwarg, scoped to request.org.
    Raises 404 if not found or doesn't belong to org.
    """
    org = view.request.org
    project = get_object_or_404(
        Project,
        pk=view.kwargs["project_pk"],
        organization=org,
        is_deleted=False,
    )
    if check_archived and project.archived:
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied(_("This project is archived. Unarchive it to make changes."))
    return project


# ─────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────

class ProjectViewSet(viewsets.ModelViewSet):
    """
    CRUD for projects scoped to the current org.

    GET    /projects/           list (with task_count annotation)
    POST   /projects/           create
    GET    /projects/{id}/      retrieve
    PATCH  /projects/{id}/      update
    DELETE /projects/{id}/      soft-delete (admin only)
    POST   /projects/{id}/archive/    toggle archived flag (admin only)
    """
    filterset_class = ProjectFilter

    def get_queryset(self):
        org = self.request.org
        return (
            Project.objects
            .filter(organization=org, is_deleted=False)
            .select_related("owner", "organization")
            .annotate(
                task_count=Count("tasks", filter=Q(tasks__is_deleted=False)),
                status_count=Count("statuses"),
            )
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return ProjectListSerializer
        return ProjectSerializer

    def get_permissions(self):
        if self.action in ("destroy", "archive"):
            return [IsOrgAdmin()]
        return [IsOrgMember()]

    def perform_create(self, serializer):
        org = self.request.org

        # Free-tier limit: max 3 active (non-archived, non-deleted) projects.
        # Archived/deleted projects don't count — users can archive old projects
        # without being blocked from creating new ones on a paid plan.
        if org.plan == "free":
            active_count = Project.objects.filter(
                organization=org,
                is_deleted=False,
                archived=False,
            ).count()
            if active_count >= 3:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "Free plan is limited to 3 active projects. "
                    "Upgrade to Pro or Business to create more."
                )

        serializer.save(organization=org, owner=self.request.user)
        logger.info(
            "project_created",
            org_id=str(org.id),
            project_name=serializer.instance.name,
            user_id=str(self.request.user.id),
        )

    def perform_destroy(self, instance):
        instance.soft_delete()
        logger.info(
            "project_deleted",
            project_id=str(instance.id),
            deleted_by=str(self.request.user.id),
        )

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """POST /projects/{id}/archive/ — toggle archived flag."""
        project = self.get_object()
        project.archived = not project.archived
        project.save(update_fields=["archived"])
        verb = "archived" if project.archived else "unarchived"
        logger.info("project_archived", project_id=str(project.id), archived=project.archived)
        return Response({"archived": project.archived, "detail": f"Project {verb}."})


# ─────────────────────────────────────────────────────────────
# TaskStatus
# ─────────────────────────────────────────────────────────────

class TaskStatusViewSet(viewsets.ModelViewSet):
    """
    Kanban columns for a project.

    GET    /projects/{id}/statuses/            list (ordered)
    POST   /projects/{id}/statuses/            create
    PATCH  /projects/{id}/statuses/{id}/       update
    DELETE /projects/{id}/statuses/{id}/       delete
    POST   /projects/{id}/statuses/reorder/    bulk reorder
    """

    serializer_class = TaskStatusSerializer

    def get_queryset(self):
        project = _get_project(self)
        return (
            TaskStatus.objects
            .filter(project=project)
            .annotate(task_count=Count("tasks", filter=Q(tasks__is_deleted=False)))
            .order_by("order")
        )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "reorder"):
            return [IsOrgAdmin()]
        return [IsOrgMember()]

    def perform_create(self, serializer):
        project = _get_project(self, check_archived=True)
        # Default order = max existing order + 10
        max_order = TaskStatus.objects.filter(project=project).order_by("-order").values_list("order", flat=True).first()
        order = (max_order or 0) + 10
        serializer.save(project=project, order=order)

    @action(detail=False, methods=["post"])
    def reorder(self, request, project_pk=None):
        """
        POST /projects/{id}/statuses/reorder/
        Body: { "ordered_ids": ["uuid1", "uuid2", ...] }
        Reassigns `order` values (0, 10, 20, …) in the given sequence.
        """
        project = _get_project(self, check_archived=True)
        serializer = TaskStatusReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordered_ids = serializer.validated_data["ordered_ids"]

        statuses = {str(s.id): s for s in TaskStatus.objects.filter(project=project)}
        bulk_update = []
        for i, sid in enumerate(ordered_ids):
            s = statuses.get(str(sid))
            if s:
                s.order = i * 10
                bulk_update.append(s)

        TaskStatus.objects.bulk_update(bulk_update, ["order"])
        return Response({"detail": "Columns reordered."})


# ─────────────────────────────────────────────────────────────
# Label
# ─────────────────────────────────────────────────────────────

class LabelViewSet(viewsets.ModelViewSet):
    """CRUD for labels scoped to a project."""

    serializer_class = LabelSerializer

    def get_queryset(self):
        project = _get_project(self)
        return Label.objects.filter(project=project).order_by("name")

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOrgAdmin()]
        return [IsOrgMember()]

    def perform_create(self, serializer):
        project = _get_project(self)
        serializer.save(project=project)


# ─────────────────────────────────────────────────────────────
# Task
# ─────────────────────────────────────────────────────────────

class TaskViewSet(viewsets.ModelViewSet):
    """
    Task CRUD + move action for a project.

    GET    /projects/{id}/tasks/            list (filterable, paginated)
    POST   /projects/{id}/tasks/            create
    GET    /projects/{id}/tasks/{id}/       retrieve (with subtasks, comments)
    PATCH  /projects/{id}/tasks/{id}/       update
    DELETE /projects/{id}/tasks/{id}/       soft-delete
    PATCH  /projects/{id}/tasks/{id}/move/  drag-and-drop move
    """

    filterset_class = TaskFilter

    def get_queryset(self):
        project = _get_project(self)
        base_qs = (
            Task.objects
            .filter(project=project, is_deleted=False)
            .select_related("status", "assignee", "project")
            .prefetch_related("labels")
            .order_by("order", "-created_at")
        )
        if self.action == "retrieve":
            return base_qs.prefetch_related(
                "subtasks",
                "comments__author",
            )
        # For list: annotate subtask progress cheaply
        return base_qs.annotate(
            subtask_total=Count("subtasks"),
            subtask_done=Count("subtasks", filter=Q(subtasks__completed=True)),
        )

    def get_serializer_class(self):
        if self.action in ("retrieve", "create", "update", "partial_update"):
            return TaskDetailSerializer
        return TaskListSerializer

    def get_permissions(self):
        return [IsOrgMember()]

    def perform_create(self, serializer):
        project = _get_project(self, check_archived=True)
        # Default order = max + 1000 in that status column
        status_id = serializer.validated_data.get("status_id")
        max_order = (
            Task.objects
            .filter(project=project, status_id=status_id, is_deleted=False)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        order = (max_order or 0) + 1000
        instance = serializer.save(project=project, order=order)
        instance._actor = self.request.user

    def perform_destroy(self, instance):
        instance._actor = self.request.user
        instance.soft_delete()
        logger.info("task_deleted", task_id=str(instance.id), deleted_by=str(self.request.user.id))

    def perform_update(self, serializer):
        serializer.instance._actor = self.request.user
        serializer.save()

    @action(detail=True, methods=["patch"], url_path="move")
    def move(self, request, project_pk=None, pk=None):
        """
        PATCH /projects/{project_id}/tasks/{task_id}/move/
        Body: { "status_id": "<uuid>", "order": <int> }

        Updates the task's column and position. The ActivityLog signal
        picks up the status_id change automatically.
        """
        task = self.get_object()
        serializer = TaskMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task._actor = request.user
        task.status_id = serializer.validated_data["status_id"]
        task.order = serializer.validated_data["order"]
        task.save(update_fields=["status_id", "order", "updated_at"])

        return Response(TaskListSerializer(task, context={"request": request}).data)


# ─────────────────────────────────────────────────────────────
# SubTask
# ─────────────────────────────────────────────────────────────

class SubTaskViewSet(viewsets.ModelViewSet):
    """Checklist items nested under a task."""

    serializer_class = SubTaskSerializer

    def _get_task(self):
        return get_object_or_404(
            Task,
            pk=self.kwargs["task_pk"],
            project__organization=self.request.org,
            is_deleted=False,
        )

    def get_queryset(self):
        task = self._get_task()
        return SubTask.objects.filter(task=task).order_by("order", "created_at")

    def get_permissions(self):
        return [IsOrgMember()]

    def perform_create(self, serializer):
        task = self._get_task()
        max_order = SubTask.objects.filter(task=task).order_by("-order").values_list("order", flat=True).first()
        serializer.save(task=task, order=(max_order or 0) + 10)


# ─────────────────────────────────────────────────────────────
# Comment
# ─────────────────────────────────────────────────────────────

class CommentViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Comments on a task. Members can create; only the author can delete.
    No editing — keeps the audit trail clean.
    """

    serializer_class = CommentSerializer

    def _get_task(self):
        return get_object_or_404(
            Task,
            pk=self.kwargs["task_pk"],
            project__organization=self.request.org,
            is_deleted=False,
        )

    def get_queryset(self):
        task = self._get_task()
        return (
            Comment.objects
            .filter(task=task)
            .select_related("author")
            .order_by("created_at")
        )

    def get_permissions(self):
        return [IsOrgMember()]

    def perform_create(self, serializer):
        task = self._get_task()
        serializer.save(task=task, author=self.request.user)

    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        if comment.author_id != request.user.id:
            return Response(
                {"detail": _("You can only delete your own comments.")},
                status=status.HTTP_403_FORBIDDEN,
            )
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────
# ActivityLog
# ─────────────────────────────────────────────────────────────

class ActivityLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Read-only activity feed for a task."""

    serializer_class = ActivityLogSerializer
    pagination_class = CreatedAtCursorPagination

    def _get_task(self):
        return get_object_or_404(
            Task,
            pk=self.kwargs["task_pk"],
            project__organization=self.request.org,
            is_deleted=False,
        )

    def get_queryset(self):
        task = self._get_task()
        return (
            ActivityLog.objects
            .filter(task=task)
            .select_related("actor")
            .order_by("-created_at")
        )

    def get_permissions(self):
        return [IsOrgMember()]
