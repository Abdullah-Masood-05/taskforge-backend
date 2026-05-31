from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tasks"
    verbose_name = "Tasks"

    def ready(self):
        import apps.tasks.signals  # noqa: F401 — register signal handlers
