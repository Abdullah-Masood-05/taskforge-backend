"""
ActivityLog tests — signal-based creation, activity endpoint.
"""
import pytest
from rest_framework import status

from apps.accounts.tests.factories import MembershipFactory

from .factories import ProjectFactory, TaskFactory, TaskStatusFactory

pytestmark = pytest.mark.django_db


def _setup(authenticated_client):
    client, user = authenticated_client
    membership = MembershipFactory(user=user, role="member")
    org = membership.organization
    project = ProjectFactory(organization=org)
    return client, user, org, project


def activity_url(task_pk):
    return f"/api/v1/tasks/{task_pk}/activity/"


def task_move_url(project_pk, task_pk):
    return f"/api/v1/projects/{project_pk}/tasks/{task_pk}/move/"


class TestActivityLog:
    def test_task_creation_logs_created_event(self, authenticated_client):
        from apps.tasks.models import ActivityLog
        client, user, org, project = _setup(authenticated_client)
        s = TaskStatusFactory(project=project)

        response = client.post(
            f"/api/v1/projects/{project.pk}/tasks/",
            {"title": "New Task", "status_id": str(s.pk)},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        task_id = response.json()["id"]
        assert ActivityLog.objects.filter(task_id=task_id, verb="created").exists()

    def test_status_change_logs_status_changed(self, authenticated_client):
        from apps.tasks.models import ActivityLog
        client, user, org, project = _setup(authenticated_client)
        s1 = TaskStatusFactory(project=project)
        s2 = TaskStatusFactory(project=project)
        task = TaskFactory(project=project, status=s1)

        client.patch(
            task_move_url(project.pk, task.pk),
            {"status_id": str(s2.pk), "order": 0},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        log = ActivityLog.objects.filter(task=task, verb="status_changed").first()
        assert log is not None
        assert str(log.new_value["value"]) == str(s2.pk)
        assert str(log.old_value["value"]) == str(s1.pk)

    def test_activity_endpoint_returns_logs(self, authenticated_client):
        from apps.tasks.models import ActivityLog
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)
        # Manually create a log entry
        ActivityLog.objects.create(
            task=task, actor=user, verb="created", new_value={"title": task.title}
        )

        response = client.get(activity_url(task.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        # Cursor pagination: no "count"; assert on the results page instead.
        assert len(response.json()["results"]) >= 1

    def test_activity_endpoint_cross_org_forbidden(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        other_task = TaskFactory()  # different org

        response = client.get(
            activity_url(other_task.pk),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_priority_change_creates_log(self, authenticated_client):
        from apps.tasks.models import ActivityLog
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project, priority="low")

        client.patch(
            f"/api/v1/projects/{project.pk}/tasks/{task.pk}/",
            {"priority": "urgent"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        assert ActivityLog.objects.filter(task=task, verb="priority_changed").exists()
