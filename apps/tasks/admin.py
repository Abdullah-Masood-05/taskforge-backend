from django.contrib import admin
from .models import ActivityLog, Comment, Label, Project, SubTask, Task, TaskStatus


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "owner", "archived", "is_deleted", "created_at"]
    list_filter = ["archived", "is_deleted", "organization"]
    search_fields = ["name", "organization__name", "owner__email"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at"]
    raw_id_fields = ["organization", "owner"]


@admin.register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "color", "order"]
    list_filter = ["project"]
    search_fields = ["name", "project__name"]
    ordering = ["project", "order"]
    readonly_fields = ["id"]


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "color"]
    list_filter = ["project"]
    search_fields = ["name", "project__name"]
    readonly_fields = ["id"]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = [
        "reference_display", "title", "project", "status",
        "assignee", "priority", "due_date", "is_deleted",
    ]
    list_filter = ["priority", "is_deleted", "project", "status"]
    search_fields = ["title", "description", "assignee__email"]
    readonly_fields = ["id", "reference", "created_at", "updated_at", "deleted_at"]
    raw_id_fields = ["project", "status", "assignee"]
    filter_horizontal = ["labels"]

    @admin.display(description="Ref")
    def reference_display(self, obj):
        return f"TASK-{obj.reference}" if obj.reference else "—"


@admin.register(SubTask)
class SubTaskAdmin(admin.ModelAdmin):
    list_display = ["title", "task", "completed", "order"]
    list_filter = ["completed"]
    search_fields = ["title", "task__title"]
    readonly_fields = ["id", "created_at"]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["author", "task", "created_at"]
    search_fields = ["author__email", "task__title", "body"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["task", "author"]


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ["verb", "task", "actor", "created_at"]
    list_filter = ["verb"]
    search_fields = ["task__title", "actor__email"]
    readonly_fields = ["id", "task", "actor", "verb", "old_value", "new_value", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
