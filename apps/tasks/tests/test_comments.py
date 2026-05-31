"""
Comment endpoint tests — create, list, author-only delete.
"""
import pytest
from rest_framework import status

from apps.accounts.tests.factories import MembershipFactory, UserFactory
from .factories import CommentFactory, ProjectFactory, TaskFactory, TaskStatusFactory

pytestmark = pytest.mark.django_db


def _setup(authenticated_client, role="member"):
    client, user = authenticated_client
    membership = MembershipFactory(user=user, role=role)
    org = membership.organization
    project = ProjectFactory(organization=org)
    return client, user, org, project


def comments_url(task_pk):
    return f"/api/v1/tasks/{task_pk}/comments/"


def comment_detail_url(task_pk, comment_pk):
    return f"/api/v1/tasks/{task_pk}/comments/{comment_pk}/"


class TestComments:
    def test_create_comment(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)

        response = client.post(
            comments_url(task.pk),
            {"body": "This needs more context."},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["body"] == "This needs more context."
        assert data["author"]["email"] == user.email
        assert data["is_own"] is True

    def test_list_comments(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)
        CommentFactory(task=task)
        CommentFactory(task=task)

        response = client.get(comments_url(task.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2

    def test_author_can_delete_own_comment(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)
        comment = CommentFactory(task=task, author=user)

        response = client.delete(
            comment_detail_url(task.pk, comment.pk),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_non_author_cannot_delete_comment(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)
        other_user = UserFactory()
        comment = CommentFactory(task=task, author=other_user)

        response = client.delete(
            comment_detail_url(task.pk, comment.pk),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_org_task_comment_forbidden(self, authenticated_client):
        """Cannot comment on a task from another org."""
        client, user, org, project = _setup(authenticated_client)
        other_task = TaskFactory()  # different org

        response = client.post(
            comments_url(other_task.pk),
            {"body": "Sneaky"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_is_own_false_for_others_comment(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project)
        other_author = UserFactory()
        MembershipFactory(user=other_author, organization=org)
        CommentFactory(task=task, author=other_author)

        response = client.get(comments_url(task.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        comments = response.json()["results"]
        assert comments[0]["is_own"] is False
