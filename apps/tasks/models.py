"""
Task management models — the core of Phase 2.

Model hierarchy:
  Organization (Phase 1)
  └── Project
      ├── TaskStatus   (Kanban columns, ordered)
      ├── Label        (colour tags for tasks)
      └── Task
          ├── SubTask
          ├── Comment
          └── ActivityLog

Design decisions:
  - All PKs are UUID, consistent with Phase 1.
  - Every model carries an `organization` or reaches one via FK chain.
  - Task.reference is a per-project sequential integer (TASK-1, TASK-2 …).
    It is set by a post_save signal (see signals.py) on first creation only.
    It is display-only — never used in API URLs.
  - ActivityLog is written from a post_save signal comparing pre/post values,
    NOT solely from the viewset, so bulk updates / Celery tasks are covered.
    Known limitation: the signal uses `update_fields` awareness, so callers
    should always pass update_fields when doing partial saves to avoid
    false-positive log entries.
"""
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

# ─────────────────────────────────────────────────────────────
# Enums / Choices
# ─────────────────────────────────────────────────────────────

class Priority(models.TextChoices):
    LOW    = "low",    _("Low")
    MEDIUM = "medium", _("Medium")
    HIGH   = "high",   _("High")
    URGENT = "urgent", _("Urgent")


class ProjectStatus(models.TextChoices):
    PLANNING    = "planning",    _("Planning")
    IN_PROGRESS = "in_progress", _("In Progress")
    ON_HOLD     = "on_hold",     _("On Hold")
    COMPLETED   = "completed",   _("Completed")


# ─────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────

class Project(models.Model):
    """
    A project groups tasks under an organization.

    Soft-delete mirrors the org pattern: is_deleted flag + deleted_at timestamp.
    Archived projects are read-only for members (admins can un-archive).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("name"), max_length=200)
    description = models.TextField(_("description"), blank=True)

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="projects",
        verbose_name=_("organization"),
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_projects",
        verbose_name=_("owner"),
    )

    # Planning metadata (drives the project header + dashboard)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=ProjectStatus.choices,
        default=ProjectStatus.PLANNING,
        db_index=True,
    )
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    due_date = models.DateField(_("due date"), null=True, blank=True)
    progress_override = models.PositiveSmallIntegerField(
        _("progress override"),
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
        help_text=_(
            "Manually pinned progress (0–100). When null, progress is computed "
            "from the share of tasks sitting in a terminal status column."
        ),
    )

    # State flags
    archived = models.BooleanField(_("archived"), default=False, db_index=True)
    is_deleted = models.BooleanField(_("deleted"), default=False, db_index=True)
    deleted_at = models.DateTimeField(_("deleted at"), null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("project")
        verbose_name_plural = _("projects")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "archived"], name="project_org_archived_idx"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def progress_percent(self) -> int:
        """
        Completion percentage for the project header progress bar.

        progress_override wins when set; otherwise computed as the share of
        non-deleted tasks whose status column is flagged is_terminal.
        """
        if self.progress_override is not None:
            return self.progress_override
        agg = self.tasks.filter(is_deleted=False).aggregate(
            total=models.Count("id"),
            done=models.Count("id", filter=models.Q(status__is_terminal=True)),
        )
        total = agg["total"] or 0
        if not total:
            return 0
        return round(agg["done"] * 100 / total)

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])


# ─────────────────────────────────────────────────────────────
# TaskStatus (Kanban columns)
# ─────────────────────────────────────────────────────────────

class TaskStatus(models.Model):
    """
    An ordered Kanban column for a project.

    `order` determines left-to-right column display.
    Gaps are allowed (e.g. 0, 10, 20) to make drag-and-drop reordering
    cheap — no need to renumber all siblings on every move.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("name"), max_length=100)
    color = models.CharField(
        _("color"),
        max_length=7,
        default="#6366f1",
        help_text=_("Hex colour code, e.g. #6366f1"),
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="statuses",
        verbose_name=_("project"),
    )
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)
    is_terminal = models.BooleanField(
        _("terminal"),
        default=False,
        help_text=_(
            "Tasks in this column count as completed for project progress "
            "and velocity analytics (e.g. a 'Done' column)."
        ),
    )

    class Meta:
        verbose_name = _("task status")
        verbose_name_plural = _("task statuses")
        ordering = ["order"]
        indexes = [
            models.Index(fields=["project", "order"], name="status_project_order_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name"],
                name="unique_status_name_per_project",
            )
        ]

    def __str__(self) -> str:
        return f"{self.project.name} › {self.name}"


# ─────────────────────────────────────────────────────────────
# Label
# ─────────────────────────────────────────────────────────────

class Label(models.Model):
    """Colour tag that can be applied to multiple tasks in a project."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("name"), max_length=60)
    color = models.CharField(_("color"), max_length=7, default="#6366f1")
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="labels",
        verbose_name=_("project"),
    )

    class Meta:
        verbose_name = _("label")
        verbose_name_plural = _("labels")
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name"],
                name="unique_label_name_per_project",
            )
        ]

    def __str__(self) -> str:
        return self.name


# ─────────────────────────────────────────────────────────────
# Task
# ─────────────────────────────────────────────────────────────

class Task(models.Model):
    """
    A task card on the Kanban board.

    `reference` is a per-project sequential integer set by a post_save
    signal (signals.py) on first creation only. Used as a display label
    (e.g. TASK-42) — not used in API URLs.

    `order` controls the vertical position of the card within its column.
    Gaps (0, 1000, 2000 …) make reordering cheap.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.PositiveIntegerField(
        _("reference"),
        null=True,
        blank=True,
        editable=False,
        help_text=_("Auto-assigned sequential number per project. Display only."),
    )

    title = models.CharField(_("title"), max_length=500)
    description = models.TextField(_("description"), blank=True)

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name=_("project"),
    )
    status = models.ForeignKey(
        TaskStatus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        verbose_name=_("status"),
    )
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="assigned_tasks",
        verbose_name=_("assignees"),
    )
    labels = models.ManyToManyField(
        Label,
        blank=True,
        related_name="tasks",
        verbose_name=_("labels"),
    )

    start_date = models.DateField(_("start date"), null=True, blank=True)
    due_date = models.DateField(_("due date"), null=True, blank=True)
    progress_percent = models.PositiveSmallIntegerField(
        _("progress percent"),
        default=0,
        validators=[MaxValueValidator(100)],
        help_text=_(
            "Manual completion indicator (0–100) shown on cards while the "
            "task sits in a non-terminal column."
        ),
    )
    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
        db_index=True,
    )
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)

    # Soft delete
    is_deleted = models.BooleanField(_("deleted"), default=False, db_index=True)
    deleted_at = models.DateTimeField(_("deleted at"), null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("task")
        verbose_name_plural = _("tasks")
        ordering = ["order", "-created_at"]
        indexes = [
            models.Index(fields=["project", "status"], name="task_project_status_idx"),
            models.Index(fields=["project", "order"], name="task_project_order_idx"),
            models.Index(fields=["project", "priority"], name="task_project_priority_idx"),
        ]

    def __str__(self) -> str:
        ref = f"TASK-{self.reference}" if self.reference else str(self.id)[:8]
        return f"{ref}: {self.title}"

    @property
    def assignee(self):
        """
        First assignee (by assignment order), for backward compatibility with
        single-assignee clients. Prefer `assignees` in new code.
        """
        link = (
            self.assignees.through.objects
            .filter(task=self)
            .order_by("id")
            .select_related("user")
            .first()
        )
        return link.user if link else None

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])


# ─────────────────────────────────────────────────────────────
# SubTask
# ─────────────────────────────────────────────────────────────

class SubTask(models.Model):
    """A checklist item within a Task."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(_("title"), max_length=500)
    completed = models.BooleanField(_("completed"), default=False, db_index=True)
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="subtasks",
        verbose_name=_("task"),
    )
    order = models.PositiveIntegerField(_("order"), default=0)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("subtask")
        verbose_name_plural = _("subtasks")
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["task", "order"], name="subtask_task_order_idx"),
        ]

    def __str__(self) -> str:
        return self.title


# ─────────────────────────────────────────────────────────────
# Comment
# ─────────────────────────────────────────────────────────────

class Comment(models.Model):
    """A comment thread item on a Task."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("task"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_comments",
        verbose_name=_("author"),
    )
    body = models.TextField(_("body"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("comment")
        verbose_name_plural = _("comments")
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Comment by {self.author.email} on {self.task}"


# ─────────────────────────────────────────────────────────────
# ActivityLog
# ─────────────────────────────────────────────────────────────

class ActivityLog(models.Model):
    """
    Immutable audit trail for Task changes.

    Written by signals.py (post_save on Task) comparing old vs new values.
    This ensures changes from any code path — viewsets, Celery tasks,
    management commands — are all captured.

    Known limitation: if a Task is saved with update_fields that does not
    include the tracked field, the signal cannot detect the change because
    Django's post_save does not re-fetch the pre-save state. Callers should
    pass update_fields precisely, which is already the project convention.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="activity_logs",
        verbose_name=_("task"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_activity",
        verbose_name=_("actor"),
    )
    verb = models.CharField(
        _("verb"),
        max_length=60,
        help_text=_("e.g. 'status_changed', 'assignee_changed', 'created'"),
    )
    old_value = models.JSONField(_("old value"), null=True, blank=True)
    new_value = models.JSONField(_("new value"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("activity log")
        verbose_name_plural = _("activity logs")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.actor} {self.verb} on {self.task}"


# ─────────────────────────────────────────────────────────────
# Attachment
# ─────────────────────────────────────────────────────────────

class Attachment(models.Model):
    """
    A file attached to a Task.

    Design decisions:
    - Stored in apps.tasks (not notifications) to avoid circular imports,
      since apps.notifications signals listen to Task post_save.
    - `file_key` stores the S3 object key (e.g. "attachments/org/task/file.pdf")
      or the relative local path when running without S3.
    - Presigned upload/download URLs are generated on-the-fly in the view,
      never stored — they expire after AWS_PRESIGNED_EXPIRY seconds.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("task"),
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_attachments",
        verbose_name=_("uploaded by"),
    )
    file_name = models.CharField(_("file name"), max_length=255)
    file_key = models.CharField(
        _("file key"),
        max_length=500,
        help_text=_("S3 object key or local relative path"),
    )
    file_size = models.PositiveIntegerField(_("file size (bytes)"))
    content_type = models.CharField(_("content type"), max_length=100)
    created_at = models.DateTimeField(_("uploaded at"), auto_now_add=True)

    class Meta:
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["task"], name="attachment_task_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.file_name} on {self.task}"
