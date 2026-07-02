"""
django-filter FilterSets for the tasks app.
"""
import django_filters
from django.db.models import Q

from .models import Project, Task


class TaskFilter(django_filters.FilterSet):
    """
    Supports filtering tasks by status, assignee, priority, label, due-date range,
    and free-text search over title + description.

    Usage examples:
      ?status=<uuid>
      ?assignee=<uuid>
      ?priority=high
      ?label=<uuid>
      ?due_before=2025-12-31
      ?due_after=2025-01-01
      ?search=login+bug
      ?unassigned=true
    """
    status    = django_filters.UUIDFilter(field_name="status__id")
    assignee  = django_filters.UUIDFilter(field_name="assignees__id")
    priority  = django_filters.ChoiceFilter(
        choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("urgent", "Urgent")]
    )
    label      = django_filters.UUIDFilter(field_name="labels__id", label="Label ID")
    due_before = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    due_after  = django_filters.DateFilter(field_name="due_date", lookup_expr="gte")
    unassigned = django_filters.BooleanFilter(
        field_name="assignees", lookup_expr="isnull", label="Unassigned only"
    )
    search = django_filters.CharFilter(method="filter_search", label="Search")

    class Meta:
        model = Task
        fields = [
            "status", "assignee", "priority", "label",
            "due_before", "due_after", "unassigned", "search",
        ]

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(title__icontains=value) | Q(description__icontains=value)
        )


class ProjectFilter(django_filters.FilterSet):
    archived = django_filters.BooleanFilter()
    search   = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Project
        fields = ["archived", "search"]
