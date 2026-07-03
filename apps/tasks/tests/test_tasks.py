"""
Task endpoint tests — CRUD, filtering, move, reference field, cross-org isolation.
"""
import pytest
from rest_framework import status

from apps.accounts.tests.factories import MembershipFactory, UserFactory

from .factories import LabelFactory, ProjectFactory, TaskFactory, TaskStatusFactory

pytestmark = pytest.mark.django_db


def _setup(authenticated_client, role="member"):
    client, user = authenticated_client
    membership = MembershipFactory(user=user, role=role)
    org = membership.organization
    project = ProjectFactory(organization=org, owner=user)
    return client, user, org, project


def tasks_list_url(project_pk):
    return f"/api/v1/projects/{project_pk}/tasks/"


def task_detail_url(project_pk, task_pk):
    return f"/api/v1/projects/{project_pk}/tasks/{task_pk}/"


def task_move_url(project_pk, task_pk):
    return f"/api/v1/projects/{project_pk}/tasks/{task_pk}/move/"


class TestTaskCRUD:
    def test_create_task(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        s = TaskStatusFactory(project=project)

        response = client.post(
            tasks_list_url(project.pk),
            {"title": "Fix login bug", "priority": "high", "status_id": str(s.pk)},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["title"] == "Fix login bug"
        # Reference should be auto-assigned
        assert data["reference_label"] is not None
        assert data["reference_label"].startswith("TASK-")

    def test_reference_increments_per_project(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        s = TaskStatusFactory(project=project)

        r1 = client.post(
            tasks_list_url(project.pk),
            {"title": "Task 1", "status_id": str(s.pk)},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        r2 = client.post(
            tasks_list_url(project.pk),
            {"title": "Task 2", "status_id": str(s.pk)},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        ref1 = int(r1.json()["reference_label"].replace("TASK-", ""))
        ref2 = int(r2.json()["reference_label"].replace("TASK-", ""))
        assert ref2 == ref1 + 1

    def test_list_tasks_in_project(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        TaskFactory(project=project)
        TaskFactory(project=project)
        TaskFactory()  # different project — must not appear

        response = client.get(tasks_list_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2

    def test_retrieve_task_includes_subtasks_and_comments(self, authenticated_client):
        from .factories import CommentFactory, SubTaskFactory
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)
        SubTaskFactory(task=task)
        CommentFactory(task=task)

        response = client.get(
            task_detail_url(project.pk, task.pk),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["subtasks"]) == 1
        assert len(data["comments"]) == 1

    def test_update_task(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project, priority="low")

        response = client.patch(
            task_detail_url(project.pk, task.pk),
            {"priority": "urgent"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

    def test_soft_delete_task(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)

        response = client.delete(
            task_detail_url(project.pk, task.pk),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        task.refresh_from_db()
        assert task.is_deleted is True

    def test_deleted_task_not_in_list(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        TaskFactory(project=project, is_deleted=True)
        TaskFactory(project=project)

        response = client.get(tasks_list_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.json()["count"] == 1

    def test_cross_org_task_invisible(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        other_project = ProjectFactory()  # different org
        other_task = TaskFactory(project=other_project)

        response = client.get(
            task_detail_url(other_project.pk, other_task.pk),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestTaskFiltering:
    def test_filter_by_status(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        s1 = TaskStatusFactory(project=project)
        s2 = TaskStatusFactory(project=project)
        TaskFactory(project=project, status=s1)
        TaskFactory(project=project, status=s2)

        response = client.get(
            tasks_list_url(project.pk) + f"?status={s1.pk}",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.json()["count"] == 1

    def test_filter_by_priority(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        TaskFactory(project=project, priority="high")
        TaskFactory(project=project, priority="low")
        TaskFactory(project=project, priority="high")

        response = client.get(
            tasks_list_url(project.pk) + "?priority=high",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.json()["count"] == 2

    def test_filter_by_assignee(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        other_user = UserFactory()
        TaskFactory(project=project, assignees=[user])
        TaskFactory(project=project, assignees=[other_user])

        response = client.get(
            tasks_list_url(project.pk) + f"?assignee={user.pk}",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.json()["count"] == 1

    def test_filter_unassigned(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        TaskFactory(project=project)
        TaskFactory(project=project, assignees=[user])

        response = client.get(
            tasks_list_url(project.pk) + "?unassigned=true",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.json()["count"] == 1

    def test_filter_by_label(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        label = LabelFactory(project=project)
        t1 = TaskFactory(project=project)
        t1.labels.add(label)
        TaskFactory(project=project)  # no label

        response = client.get(
            tasks_list_url(project.pk) + f"?label={label.pk}",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.json()["count"] == 1

    def test_search_by_title(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        TaskFactory(project=project, title="Fix authentication bug")
        TaskFactory(project=project, title="Update styles")

        response = client.get(
            tasks_list_url(project.pk) + "?search=authentication",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.json()["count"] == 1


class TestTaskMove:
    def test_move_task_to_new_column(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        s1 = TaskStatusFactory(project=project, order=0)
        s2 = TaskStatusFactory(project=project, order=10)
        task = TaskFactory(project=project, status=s1, order=0)

        response = client.patch(
            task_move_url(project.pk, task.pk),
            {"status_id": str(s2.pk), "order": 500},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        task.refresh_from_db()
        assert str(task.status_id) == str(s2.pk)
        assert task.order == 500

    def test_move_creates_activity_log(self, authenticated_client):
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
        assert ActivityLog.objects.filter(task=task, verb="status_changed").exists()
