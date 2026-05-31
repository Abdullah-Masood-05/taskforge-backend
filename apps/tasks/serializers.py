"""
Serializers for the tasks app.

Serializer naming convention:
  *ListSerializer  — compact, used in list endpoints (low DB cost)
  *Serializer      — full detail, used in retrieve/create/update
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import ActivityLog, Comment, Label, Project, SubTask, Task, TaskStatus

User = get_user_model()


# ─────────────────────────────────────────────────────────────
# User summary (embedded in tasks / comments)
# ─────────────────────────────────────────────────────────────

class UserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    avatar = serializers.ImageField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "avatar"]
        read_only_fields = fields


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
            "owner_email", "task_count", "status_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "owner_email", "task_count", "status_count", "created_at", "updated_at"]


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
    """
    assignee = UserSummarySerializer(read_only=True)
    labels = LabelSerializer(many=True, read_only=True)
    status_id = serializers.UUIDField(allow_null=True)
    reference_label = serializers.SerializerMethodField()
    subtask_total = serializers.IntegerField(read_only=True)
    subtask_done = serializers.IntegerField(read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "reference_label", "title", "priority",
            "status_id", "assignee", "labels",
            "due_date", "order",
            "subtask_total", "subtask_done",
            "created_at",
        ]
        read_only_fields = ["id", "reference_label", "subtask_total", "subtask_done", "created_at"]

    def get_reference_label(self, obj) -> str | None:
        if obj.reference:
            return f"TASK-{obj.reference}"
        return None


# ─────────────────────────────────────────────────────────────
# Task — full detail
# ─────────────────────────────────────────────────────────────

class TaskDetailSerializer(serializers.ModelSerializer):
    assignee = UserSummarySerializer(read_only=True)
    assignee_id = serializers.UUIDField(
        write_only=True, allow_null=True, required=False,
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
            "priority", "due_date", "order",
            "status", "status_id",
            "assignee", "assignee_id",
            "labels", "label_ids",
            "subtasks", "comments",
            "is_deleted", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reference_label", "is_deleted", "created_at", "updated_at",
        ]

    def get_reference_label(self, obj) -> str | None:
        return f"TASK-{obj.reference}" if obj.reference else None

    def _set_actor(self, instance):
        """Attach the request user to the instance for signal attribution."""
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            instance._actor = request.user

    def create(self, validated_data):
        label_ids = validated_data.pop("label_ids", [])
        instance = super().create(validated_data)
        if label_ids:
            instance.labels.set(label_ids)
        self._set_actor(instance)
        return instance

    def update(self, instance, validated_data):
        label_ids = validated_data.pop("label_ids", None)
        self._set_actor(instance)
        instance = super().update(instance, validated_data)
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
