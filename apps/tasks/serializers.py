"""
Serializers for the tasks app.

Serializer naming convention:
  *ListSerializer  — compact, used in list endpoints (low DB cost)
  *Serializer      — full detail, used in retrieve/create/update
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from rest_framework import serializers

from .models import (
    ActivityLog,
    Comment,
    Label,
    Priority,
    Project,
    ProjectStatus,
    SubTask,
    Task,
    TaskStatus,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────
# User summary (embedded in tasks / comments)
# ─────────────────────────────────────────────────────────────

class UserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    avatar = serializers.ImageField(read_only=True)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "avatar", "avatar_url"]
        read_only_fields = fields

    def get_avatar_url(self, obj) -> str | None:
        """External avatar_url wins; falls back to the uploaded avatar file."""
        if getattr(obj, "avatar_url", ""):
            return obj.avatar_url
        if obj.avatar:
            try:
                return obj.avatar.url
            except ValueError:
                return None
        return None


# ─────────────────────────────────────────────────────────────
# Project
# ─────────────────────────────────────────────────────────────

class ProjectListSerializer(serializers.ModelSerializer):
    task_count = serializers.IntegerField(read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = Project
        fields = [
            "id", "name", "description", "archived",
            "status", "priority", "due_date",
            "owner_email", "task_count", "created_at",
        ]
        read_only_fields = ["id", "owner_email", "task_count", "created_at"]


class ProjectSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    task_count = serializers.IntegerField(read_only=True)
    status_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Project
        fields = [
            "id", "name", "description", "archived",
            "status", "priority", "due_date", "progress_override",
            "owner_email", "task_count", "status_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "owner_email", "task_count", "status_count", "created_at", "updated_at"]


class ProjectDetailSerializer(ProjectSerializer):
    """
    Full project header payload: nested owner, computed progress and
    per-column task counts for the board dashboard.
    """
    owner = UserSummarySerializer(read_only=True)
    progress_percent = serializers.IntegerField(read_only=True)
    status_counts = serializers.SerializerMethodField()

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + [
            "owner", "progress_percent", "status_counts",
        ]
        read_only_fields = ProjectSerializer.Meta.read_only_fields + [
            "owner", "progress_percent", "status_counts",
        ]

    def get_status_counts(self, obj) -> dict:
        """{status_name: non-deleted task count}, in column order."""
        rows = (
            TaskStatus.objects
            .filter(project=obj)
            .annotate(n=Count("tasks", filter=Q(tasks__is_deleted=False)))
            .order_by("order")
            .values_list("name", "n")
        )
        return dict(rows)


# ─────────────────────────────────────────────────────────────
# TaskStatus
# ─────────────────────────────────────────────────────────────

class TaskStatusSerializer(serializers.ModelSerializer):
    task_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = TaskStatus
        fields = ["id", "name", "color", "order", "task_count"]
        read_only_fields = ["id", "task_count"]


class TaskStatusReorderSerializer(serializers.Serializer):
    """Body for POST /projects/{id}/statuses/reorder/"""
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )


# ─────────────────────────────────────────────────────────────
# Label
# ─────────────────────────────────────────────────────────────

class LabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "color"]
        read_only_fields = ["id"]


# ─────────────────────────────────────────────────────────────
# SubTask
# ─────────────────────────────────────────────────────────────

class SubTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubTask
        fields = ["id", "title", "completed", "order", "created_at"]
        read_only_fields = ["id", "created_at"]


# ─────────────────────────────────────────────────────────────
# Comment
# ─────────────────────────────────────────────────────────────

class CommentSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)
    is_own = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "author", "body", "is_own", "created_at", "updated_at"]
        read_only_fields = ["id", "author", "is_own", "created_at", "updated_at"]

    def get_is_own(self, obj) -> bool:
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.author_id == request.user.id
        return False


# ─────────────────────────────────────────────────────────────
# ActivityLog
# ─────────────────────────────────────────────────────────────

class ActivityLogSerializer(serializers.ModelSerializer):
    actor = UserSummarySerializer(read_only=True)

    class Meta:
        model = ActivityLog
        fields = ["id", "actor", "verb", "old_value", "new_value", "created_at"]
        read_only_fields = fields


# ─────────────────────────────────────────────────────────────
# Task — list (card view)
# ─────────────────────────────────────────────────────────────

class TaskListSerializer(serializers.ModelSerializer):
    """
    Compact serializer used in list and Kanban board endpoints.
    Avoids heavy nested fetches — subtask progress is a computed pair.

    `assignee` (first assignee) is kept for backward compatibility with
    single-assignee clients; new clients should use `assignees`.
    """
    assignee = serializers.SerializerMethodField()
    assignees = UserSummarySerializer(many=True, read_only=True)
    labels = LabelSerializer(many=True, read_only=True)
    status_id = serializers.UUIDField(allow_null=True)
    reference_label = serializers.SerializerMethodField()
    subtask_total = serializers.IntegerField(read_only=True)
    subtask_done = serializers.IntegerField(read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "reference_label", "title", "priority",
            "status_id", "assignee", "assignees", "labels",
            "start_date", "due_date", "progress_percent", "order",
            "subtask_total", "subtask_done",
            "created_at",
        ]
        read_only_fields = ["id", "reference_label", "subtask_total", "subtask_done", "created_at"]

    def get_reference_label(self, obj) -> str | None:
        if obj.reference:
            return f"TASK-{obj.reference}"
        return None

    def get_assignee(self, obj):
        """First assignee, using the prefetched cache (no extra query)."""
        users = list(obj.assignees.all())
        if not users:
            return None
        return UserSummarySerializer(users[0], context=self.context).data


# ─────────────────────────────────────────────────────────────
# Task — full detail
# ─────────────────────────────────────────────────────────────

class TaskDetailSerializer(serializers.ModelSerializer):
    assignee = serializers.SerializerMethodField()
    assignees = UserSummarySerializer(many=True, read_only=True)
    # Legacy single-assignee write field — kept so older clients keep working.
    assignee_id = serializers.UUIDField(
        write_only=True, allow_null=True, required=False,
    )
    assignee_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        allow_empty=True,
    )
    status = TaskStatusSerializer(read_only=True)
    status_id = serializers.UUIDField(allow_null=True, required=False)
    labels = LabelSerializer(many=True, read_only=True)
    label_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
        allow_empty=True,
    )
    subtasks = SubTaskSerializer(many=True, read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    reference_label = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "reference_label", "title", "description",
            "priority", "start_date", "due_date", "progress_percent", "order",
            "status", "status_id",
            "assignee", "assignee_id",
            "assignees", "assignee_ids",
            "labels", "label_ids",
            "subtasks", "comments",
            "is_deleted", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reference_label", "is_deleted", "created_at", "updated_at",
        ]

    def get_reference_label(self, obj) -> str | None:
        return f"TASK-{obj.reference}" if obj.reference else None

    def get_assignee(self, obj):
        """First assignee, for backward compatibility."""
        users = list(obj.assignees.all())
        if not users:
            return None
        return UserSummarySerializer(users[0], context=self.context).data

    def _validate_org_members(self, user_ids):
        request = self.context.get("request")
        org = getattr(request, "org", None)
        if org is None or not user_ids:
            return
        from apps.organizations.models import Membership
        member_ids = set(
            Membership.objects
            .filter(organization=org, user_id__in=user_ids)
            .values_list("user_id", flat=True)
        )
        if any(uid not in member_ids for uid in user_ids):
            raise serializers.ValidationError(
                "All assignees must be members of this organization."
            )

    def validate_assignee_id(self, value):
        """Assignee must be a member of the current org (prevents FK 500s)."""
        if value is not None:
            self._validate_org_members([value])
        return value

    def validate_assignee_ids(self, value):
        self._validate_org_members(value or [])
        return value

    def validate_status_id(self, value):
        """Status column must belong to the task's project (prevents FK 500s)."""
        if value is None:
            return value
        view = self.context.get("view")
        project_pk = view.kwargs.get("project_pk") if view else None
        if project_pk is None:
            return value
        if not TaskStatus.objects.filter(project_id=project_pk, id=value).exists():
            raise serializers.ValidationError(
                "Status column does not belong to this project."
            )
        return value

    def _set_actor(self, instance):
        """Attach the request user to the instance for signal attribution."""
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            instance._actor = request.user

    @staticmethod
    def _pop_assignee_ids(validated_data):
        """
        Resolve the desired assignee set from either `assignee_ids` (new) or
        the legacy `assignee_id`. Returns None when neither was provided.
        """
        has_many = "assignee_ids" in validated_data
        many = validated_data.pop("assignee_ids", None)
        has_legacy = "assignee_id" in validated_data
        legacy = validated_data.pop("assignee_id", None)
        if has_many:
            return many
        if has_legacy:
            return [legacy] if legacy is not None else []
        return None

    def create(self, validated_data):
        label_ids = validated_data.pop("label_ids", [])
        assignee_ids = self._pop_assignee_ids(validated_data)
        instance = super().create(validated_data)
        self._set_actor(instance)
        if assignee_ids:
            instance.assignees.set(assignee_ids)
        if label_ids:
            instance.labels.set(label_ids)
        return instance

    def update(self, instance, validated_data):
        label_ids = validated_data.pop("label_ids", None)
        assignee_ids = self._pop_assignee_ids(validated_data)
        self._set_actor(instance)
        instance = super().update(instance, validated_data)
        if assignee_ids is not None:
            instance.assignees.set(assignee_ids)
        if label_ids is not None:
            instance.labels.set(label_ids)
        return instance


# ─────────────────────────────────────────────────────────────
# Task move (drag-and-drop)
# ─────────────────────────────────────────────────────────────

class TaskMoveSerializer(serializers.Serializer):
    """Body for PATCH /tasks/{id}/move/"""
    status_id = serializers.UUIDField(allow_null=True)
    order = serializers.IntegerField(min_value=0)


# ─────────────────────────────────────────────────────────────
# Project import (JSON interchange format)
# ─────────────────────────────────────────────────────────────
# Shape mirrors the export endpoint: statuses/labels are referenced by name
# and assignees by email, so a file exported from one environment can be
# imported into another.

class ProjectImportMetaSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(
        choices=ProjectStatus.choices, required=False, default=ProjectStatus.PLANNING,
    )
    priority = serializers.ChoiceField(
        choices=Priority.choices, required=False, default=Priority.MEDIUM,
    )
    due_date = serializers.DateField(required=False, allow_null=True, default=None)
    progress_override = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0, max_value=100,
    )


class ProjectImportStatusSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    color = serializers.CharField(max_length=7, required=False, default="#6366f1")
    order = serializers.IntegerField(required=False, default=None, allow_null=True)
    is_terminal = serializers.BooleanField(required=False, default=False)


class ProjectImportLabelSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    color = serializers.CharField(max_length=7, required=False, default="#6366f1")


class ProjectImportTaskSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=500)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.CharField(
        max_length=100, required=False, allow_null=True, default=None,
        help_text="Status column name; must appear in the file's statuses list.",
    )
    labels = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, default=list,
    )
    assignees = serializers.ListField(
        child=serializers.EmailField(), required=False, default=list,
    )
    priority = serializers.ChoiceField(
        choices=Priority.choices, required=False, default=Priority.MEDIUM,
    )
    start_date = serializers.DateField(required=False, allow_null=True, default=None)
    due_date = serializers.DateField(required=False, allow_null=True, default=None)
    progress_percent = serializers.IntegerField(
        required=False, default=0, min_value=0, max_value=100,
    )
    order = serializers.IntegerField(required=False, default=0)


class ProjectImportSerializer(serializers.Serializer):
    """Validates the whole import file before anything touches the DB."""
    format = serializers.CharField()
    version = serializers.IntegerField()
    project = ProjectImportMetaSerializer()
    statuses = ProjectImportStatusSerializer(many=True)
    labels = ProjectImportLabelSerializer(many=True, required=False, default=list)
    tasks = ProjectImportTaskSerializer(many=True, required=False, default=list)

    def validate_format(self, value):
        if value != "taskforge.project":
            raise serializers.ValidationError(
                'Unsupported file format — expected "taskforge.project".'
            )
        return value

    def validate_version(self, value):
        if value != 1:
            raise serializers.ValidationError("Unsupported format version — expected 1.")
        return value

    def validate(self, attrs):
        status_names = {s["name"] for s in attrs.get("statuses", [])}
        label_names = {label["name"] for label in attrs.get("labels", [])}
        for i, task in enumerate(attrs.get("tasks", [])):
            if task.get("status") and task["status"] not in status_names:
                raise serializers.ValidationError(
                    f'Task {i + 1} references unknown status "{task["status"]}".'
                )
            for name in task.get("labels", []):
                if name not in label_names:
                    raise serializers.ValidationError(
                        f'Task {i + 1} references unknown label "{name}".'
                    )
        return attrs
