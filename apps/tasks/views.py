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
import json
from collections import defaultdict
from datetime import timedelta

import structlog
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import IsOrgAdmin, IsOrgMember
from apps.core.pagination import CreatedAtCursorPagination

from .filters import ProjectFilter, TaskFilter
from .models import ActivityLog, Comment, Label, Project, SubTask, Task, TaskStatus
from .serializers import (
    ActivityLogSerializer,
    CommentSerializer,
    LabelSerializer,
    ProjectDetailSerializer,
    ProjectImportSerializer,
    ProjectListSerializer,
    ProjectSerializer,
    SubTaskSerializer,
    TaskDetailSerializer,
    TaskListSerializer,
    TaskMoveSerializer,
    TaskStatusReorderSerializer,
    TaskStatusSerializer,
    UserSummarySerializer,
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


def _activity_message(log, status_names: dict) -> str:
    """
    Human-readable feed line built from verb/old_value/new_value,
    e.g. 'Olivia R. updated TASK-779 — moved to In Review'.
    """
    actor = (log.actor.full_name or log.actor.email) if log.actor else "Someone"
    task = log.task
    ref = f"TASK-{task.reference}" if task.reference else "a task"
    new = (log.new_value or {}).get("value")

    if log.verb == "created":
        return f"{actor} created {ref}: {task.title}"
    if log.verb == "status_changed":
        column = status_names.get(new, "another column")
        return f"{actor} updated {ref} — moved to {column}"
    if log.verb == "assignees_changed":
        nv = log.new_value or {}
        if nv.get("added"):
            return f"{actor} assigned {', '.join(nv['added'])} to {ref}"
        if nv.get("removed"):
            return f"{actor} removed {', '.join(nv['removed'])} from {ref}"
        if nv.get("cleared"):
            return f"{actor} cleared assignees on {ref}"
        return f"{actor} changed assignees on {ref}"
    if log.verb == "priority_changed":
        return f"{actor} set {ref} priority to {(new or '').title() or '—'}"
    if log.verb == "title_changed":
        return f'{actor} renamed {ref} to "{new}"'
    if log.verb == "due_date_changed":
        return f"{actor} set {ref} due date to {new or '—'}"
    if log.verb == "start_date_changed":
        return f"{actor} set {ref} start date to {new or '—'}"
    if log.verb == "progress_changed":
        return f"{actor} updated {ref} progress to {new}%"
    return f"{actor} {log.verb.replace('_', ' ')} on {ref}"


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
                # distinct=True: both joins are multivalued — without it the
                # counts multiply (tasks × statuses) on non-trivial projects.
                task_count=Count("tasks", filter=Q(tasks__is_deleted=False), distinct=True),
                status_count=Count("statuses", distinct=True),
            )
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return ProjectListSerializer
        if self.action in ("retrieve", "update", "partial_update"):
            return ProjectDetailSerializer
        return ProjectSerializer

    def get_permissions(self):
        if self.action in ("destroy", "archive"):
            return [IsOrgAdmin()]
        return [IsOrgMember()]

    @staticmethod
    def _enforce_project_limit(org):
        """Free-tier limit: max 3 active (non-archived, non-deleted) projects."""
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

    def perform_create(self, serializer):
        org = self.request.org

        # Archived/deleted projects don't count — users can archive old projects
        # without being blocked from creating new ones on a paid plan.
        self._enforce_project_limit(org)

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

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """
        GET /projects/{id}/timeline/

        Flat list of every non-deleted task that has BOTH start_date and
        due_date, for the Gantt-style timeline panel.
        """
        project = self.get_object()
        tasks = (
            Task.objects
            .filter(
                project=project,
                is_deleted=False,
                start_date__isnull=False,
                due_date__isnull=False,
            )
            .select_related("status")
            .prefetch_related("assignees")
            .order_by("start_date", "order")
        )
        results = [
            {
                "id": str(t.id),
                "title": t.title,
                "reference_label": f"TASK-{t.reference}" if t.reference else None,
                "start_date": t.start_date.isoformat(),
                "end_date": t.due_date.isoformat(),
                "priority": t.priority,
                "progress_percent": t.progress_percent,
                "status": (
                    {
                        "id": str(t.status_id),
                        "name": t.status.name,
                        "color": t.status.color,
                        "is_terminal": t.status.is_terminal,
                    }
                    if t.status_id
                    else None
                ),
                "assignees": UserSummarySerializer(
                    t.assignees.all(), many=True, context={"request": request}
                ).data,
            }
            for t in tasks
        ]
        return Response(results)

    @action(detail=True, methods=["get"])
    def analytics(self, request, pk=None):
        """
        GET /projects/{id}/analytics/

        velocity:     last 8 ISO weeks of completed vs planned task counts.
                      completed = tasks moved into a terminal status that week
                      (from the ActivityLog), planned = tasks due that week.
        distribution: task counts grouped by priority.
        """
        project = self.get_object()

        today = timezone.localdate()
        this_monday = today - timedelta(days=today.weekday())
        week_starts = [this_monday - timedelta(weeks=i) for i in range(7, -1, -1)]
        window_start = week_starts[0]
        window_end = week_starts[-1] + timedelta(days=6)

        terminal_ids = {
            str(sid)
            for sid in TaskStatus.objects
            .filter(project=project, is_terminal=True)
            .values_list("id", flat=True)
        }

        completed_by_week: dict = defaultdict(int)
        if terminal_ids:
            logs = (
                ActivityLog.objects
                .filter(
                    task__project=project,
                    task__is_deleted=False,
                    verb="status_changed",
                    created_at__date__gte=window_start,
                )
                .values_list("created_at", "new_value")
            )
            for created_at, new_value in logs:
                if ((new_value or {}).get("value")) in terminal_ids:
                    day = timezone.localtime(created_at).date()
                    completed_by_week[day - timedelta(days=day.weekday())] += 1

        planned_by_week: dict = defaultdict(int)
        due_dates = (
            Task.objects
            .filter(
                project=project,
                is_deleted=False,
                due_date__gte=window_start,
                due_date__lte=window_end,
            )
            .values_list("due_date", flat=True)
        )
        for due in due_dates:
            planned_by_week[due - timedelta(days=due.weekday())] += 1

        velocity = [
            {
                "week_label": f"W{ws.isocalendar()[1]}",
                "week_start": ws.isoformat(),
                "completed_count": completed_by_week.get(ws, 0),
                "planned_count": planned_by_week.get(ws, 0),
            }
            for ws in week_starts
        ]

        rows = (
            Task.objects
            .filter(project=project, is_deleted=False)
            .values("priority")
            .annotate(count=Count("id"))
        )
        by_priority = {r["priority"]: r["count"] for r in rows}
        total = sum(by_priority.values())
        distribution = [
            {
                "priority": p,
                "count": by_priority.get(p, 0),
                "percent": round(by_priority.get(p, 0) * 100 / total, 1) if total else 0.0,
            }
            for p in ("urgent", "high", "medium", "low")
        ]

        return Response({"velocity": velocity, "distribution": distribution})

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        """
        GET /projects/{id}/activity/?limit=20

        Recent ActivityLog entries across ALL tasks in the project, newest
        first, each with a human-readable message for the feed.
        """
        project = self.get_object()
        try:
            limit = int(request.query_params.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, 100))

        status_names = {
            str(s.id): s.name
            for s in TaskStatus.objects.filter(project=project)
        }
        logs = (
            ActivityLog.objects
            .filter(task__project=project)
            .select_related("actor", "task")
            .order_by("-created_at")[:limit]
        )
        results = [
            {
                "id": str(log.id),
                "actor": (
                    UserSummarySerializer(log.actor, context={"request": request}).data
                    if log.actor
                    else None
                ),
                "verb": log.verb,
                "message": _activity_message(log, status_names),
                "task": {
                    "id": str(log.task_id),
                    "title": log.task.title,
                    "reference_label": (
                        f"TASK-{log.task.reference}" if log.task.reference else None
                    ),
                },
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
        return Response(results)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """
        GET /projects/{id}/export/

        Dump the project (statuses, labels, tasks with assignee emails) as a
        portable JSON file — also serves as a project template format.
        """
        project = self.get_object()
        statuses = list(TaskStatus.objects.filter(project=project).order_by("order"))
        labels = list(Label.objects.filter(project=project).order_by("name"))
        tasks = (
            Task.objects
            .filter(project=project, is_deleted=False)
            .select_related("status")
            .prefetch_related("labels", "assignees")
            .order_by("order", "created_at")
        )

        payload = {
            "format": "taskforge.project",
            "version": 1,
            "exported_at": timezone.now().isoformat(),
            "project": {
                "name": project.name,
                "description": project.description,
                "status": project.status,
                "priority": project.priority,
                "due_date": project.due_date.isoformat() if project.due_date else None,
                "progress_override": project.progress_override,
            },
            "statuses": [
                {
                    "name": s.name,
                    "color": s.color,
                    "order": s.order,
                    "is_terminal": s.is_terminal,
                }
                for s in statuses
            ],
            "labels": [{"name": lb.name, "color": lb.color} for lb in labels],
            "tasks": [
                {
                    "title": t.title,
                    "description": t.description,
                    "status": t.status.name if t.status_id else None,
                    "labels": [lb.name for lb in t.labels.all()],
                    "assignees": [u.email for u in t.assignees.all()],
                    "priority": t.priority,
                    "start_date": t.start_date.isoformat() if t.start_date else None,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                    "progress_percent": t.progress_percent,
                    "order": t.order,
                }
                for t in tasks
            ],
        }

        filename = f"{slugify(project.name) or 'project'}-export.json"
        response = HttpResponse(
            json.dumps(payload, indent=2),
            content_type="application/json",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        parser_classes=[MultiPartParser, FormParser],
    )
    def import_project(self, request):
        """
        POST /projects/import/  (multipart, file field: "file")

        Recreates a project from the JSON produced by the export endpoint.
        Users are matched (or created and added to the org) by email.
        Malformed files are rejected with a 400 and a clear error.
        """
        org = request.org

        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": 'Attach the exported JSON file under the "file" field.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > 5 * 1024 * 1024:
            return Response(
                {"detail": "Import file too large (5 MB max)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            payload = json.loads(upload.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Response(
                {"detail": "File is not valid JSON."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ProjectImportSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        self._enforce_project_limit(org)

        User = get_user_model()  # noqa: N806
        users_created = 0

        with transaction.atomic():
            meta = data["project"]
            project = Project.objects.create(
                organization=org,
                owner=request.user,
                name=meta["name"],
                description=meta.get("description", ""),
                status=meta.get("status"),
                priority=meta.get("priority"),
                due_date=meta.get("due_date"),
                progress_override=meta.get("progress_override"),
            )

            status_by_name = {}
            for i, s in enumerate(data["statuses"]):
                status_by_name[s["name"]] = TaskStatus.objects.create(
                    project=project,
                    name=s["name"],
                    color=s.get("color") or "#6366f1",
                    order=s["order"] if s.get("order") is not None else i * 10,
                    is_terminal=s.get("is_terminal", False),
                )

            label_by_name = {}
            for lb in data.get("labels", []):
                label_by_name[lb["name"]] = Label.objects.create(
                    project=project,
                    name=lb["name"],
                    color=lb.get("color") or "#6366f1",
                )

            # Match or create users by email; imported users join the org
            # as members so task assignment stays valid.
            from apps.organizations.models import MemberRole, Membership

            emails = {
                email
                for task in data.get("tasks", [])
                for email in task.get("assignees", [])
            }
            user_by_email = {}
            for email in emails:
                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "first_name": email.split("@")[0][:150].title(),
                        "is_verified": False,
                    },
                )
                if created:
                    user.set_unusable_password()
                    user.save(update_fields=["password"])
                    users_created += 1
                Membership.objects.get_or_create(
                    user=user,
                    organization=org,
                    defaults={"role": MemberRole.MEMBER, "invited_by": request.user},
                )
                user_by_email[email] = user

            for t in data.get("tasks", []):
                task = Task.objects.create(
                    project=project,
                    title=t["title"],
                    description=t.get("description", ""),
                    status=status_by_name.get(t.get("status")),
                    priority=t.get("priority"),
                    start_date=t.get("start_date"),
                    due_date=t.get("due_date"),
                    progress_percent=t.get("progress_percent", 0),
                    order=t.get("order", 0),
                )
                if t.get("assignees"):
                    task.assignees.set(
                        [user_by_email[e] for e in t["assignees"] if e in user_by_email]
                    )
                if t.get("labels"):
                    task.labels.set(
                        [label_by_name[n] for n in t["labels"] if n in label_by_name]
                    )

        logger.info(
            "project_imported",
            org_id=str(org.id),
            project_id=str(project.id),
            task_count=len(data.get("tasks", [])),
            users_created=users_created,
        )
        detail_data = ProjectDetailSerializer(
            project, context={"request": request}
        ).data
        return Response(
            {
                "project": detail_data,
                "imported": {
                    "statuses": len(data["statuses"]),
                    "labels": len(data.get("labels", [])),
                    "tasks": len(data.get("tasks", [])),
                    "users_created": users_created,
                },
            },
            status=status.HTTP_201_CREATED,
        )


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
        max_order = (
            TaskStatus.objects.filter(project=project)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
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
            .select_related("status", "project")
            .prefetch_related("labels", "assignees")
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
        max_order = (
            SubTask.objects.filter(task=task)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
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
