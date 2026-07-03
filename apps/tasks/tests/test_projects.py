"""
Project endpoint tests — CRUD, soft-delete, archive, cross-org isolation.
"""
import pytest
from rest_framework import status

from apps.accounts.tests.factories import MembershipFactory

from .factories import ProjectFactory, TaskStatusFactory

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/projects/"


def detail_url(pk):
    return f"/api/v1/projects/{pk}/"


def archive_url(pk):
    return f"/api/v1/projects/{pk}/archive/"


def _org_client(authenticated_client, role="member"):
    """Returns (client, user, org) with an active membership."""
    client, user = authenticated_client
    membership = MembershipFactory(user=user, role=role)
    org = membership.organization
    client.credentials(
        HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"],
    )
    return client, user, org


class TestProjectCRUD:
    def test_list_projects_in_org(self, authenticated_client):
        client, user, org = _org_client(authenticated_client)
        ProjectFactory(organization=org)
        ProjectFactory(organization=org)
        ProjectFactory()  # different org — must not appear

        response = client.get(LIST_URL, HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 2

    def test_create_project(self, authenticated_client):
        client, user, org = _org_client(authenticated_client)
        response = client.post(
            LIST_URL,
            {"name": "My Project", "description": "Test"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "My Project"
        assert data["owner_email"] == user.email

    def test_retrieve_project(self, authenticated_client):
        client, user, org = _org_client(authenticated_client)
        project = ProjectFactory(organization=org)

        response = client.get(detail_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        assert str(response.json()["id"]) == str(project.pk)

    def test_free_tier_project_limit(self, authenticated_client):
        """Free tier is limited to 3 active projects."""
        client, user, org = _org_client(authenticated_client)
        org.plan = "free"
        org.save()

        # Create 3 active projects
        ProjectFactory.create_batch(3, organization=org)

        # 4th project should be rejected
        response = client.post(
            LIST_URL,
            {"name": "4th Project", "description": "Test"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "limited to 3 active projects" in response.json()["message"]

    def test_free_tier_limit_ignores_archived_and_deleted(self, authenticated_client):
        """Archived and deleted projects do not count towards the free tier limit."""
        client, user, org = _org_client(authenticated_client)
        org.plan = "free"
        org.save()

        # Create 3 active projects
        ProjectFactory.create_batch(3, organization=org)

        # Create some archived and deleted projects
        ProjectFactory.create_batch(2, organization=org, archived=True)
        ProjectFactory.create_batch(2, organization=org, is_deleted=True)

        # 4th active project should still be rejected
        response = client.post(
            LIST_URL,
            {"name": "4th Project", "description": "Test"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "limited to 3 active projects" in response.json()["message"]

    def test_paid_tier_bypasses_project_limit(self, authenticated_client):
        """Pro and Business plans have unlimited projects."""
        for plan in ["pro", "business"]:
            client, user, org = _org_client(authenticated_client)
            org.plan = plan
            org.save()

            ProjectFactory.create_batch(3, organization=org)

            response = client.post(
                LIST_URL,
                {"name": "4th Project", "description": "Test"},
                HTTP_X_ORGANIZATION_SLUG=org.slug,
            )
            assert response.status_code == status.HTTP_201_CREATED

    def test_update_project(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="member")
        project = ProjectFactory(organization=org)

        response = client.patch(
            detail_url(project.pk),
            {"name": "Renamed"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Renamed"

    def test_soft_delete_project_admin_only(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="member")
        project = ProjectFactory(organization=org)

        response = client.delete(detail_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_soft_delete_project_as_admin(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="admin")
        project = ProjectFactory(organization=org)

        response = client.delete(detail_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        project.refresh_from_db()
        assert project.is_deleted is True

    def test_deleted_project_not_in_list(self, authenticated_client):
        client, user, org = _org_client(authenticated_client)
        ProjectFactory(organization=org, is_deleted=True)
        ProjectFactory(organization=org)

        response = client.get(LIST_URL, HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.json()["count"] == 1

    def test_cross_org_isolation(self, authenticated_client):
        """User from org A cannot see or modify org B's projects."""
        client, user, org = _org_client(authenticated_client)
        other_project = ProjectFactory()  # different org

        # Cannot retrieve
        response = client.get(
            detail_url(other_project.pk),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthenticated_cannot_list(self, api_client):
        response = api_client.get(LIST_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestProjectArchive:
    def test_archive_project(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="admin")
        project = ProjectFactory(organization=org, archived=False)

        response = client.post(archive_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["archived"] is True

        project.refresh_from_db()
        assert project.archived is True

    def test_unarchive_project(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="admin")
        project = ProjectFactory(organization=org, archived=True)

        response = client.post(archive_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.json()["archived"] is False

    def test_member_cannot_archive(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="member")
        project = ProjectFactory(organization=org)

        response = client.post(archive_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_archived_filter(self, authenticated_client):
        client, user, org = _org_client(authenticated_client)
        ProjectFactory(organization=org, archived=True)
        ProjectFactory(organization=org, archived=False)

        response = client.get(
            LIST_URL + "?archived=true",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.json()["count"] == 1


class TestTaskStatusViewSet:
    def statuses_url(self, project_pk):
        return f"/api/v1/projects/{project_pk}/statuses/"

    def reorder_url(self, project_pk):
        return f"/api/v1/projects/{project_pk}/statuses/reorder/"

    def test_list_statuses(self, authenticated_client):
        client, user, org = _org_client(authenticated_client)
        project = ProjectFactory(organization=org)
        TaskStatusFactory(project=project, order=0)
        TaskStatusFactory(project=project, order=10)

        response = client.get(self.statuses_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        assert results[0]["order"] <= results[1]["order"]

    def test_create_status_admin_only(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="member")
        project = ProjectFactory(organization=org)

        response = client.post(
            self.statuses_url(project.pk),
            {"name": "In Review", "color": "#f59e0b"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_create_status_as_admin(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="admin")
        project = ProjectFactory(organization=org)

        response = client.post(
            self.statuses_url(project.pk),
            {"name": "Done", "color": "#22c55e"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == "Done"

    def test_reorder_statuses(self, authenticated_client):
        client, user, org = _org_client(authenticated_client, role="admin")
        project = ProjectFactory(organization=org)
        s1 = TaskStatusFactory(project=project, order=0)
        s2 = TaskStatusFactory(project=project, order=10)
        s3 = TaskStatusFactory(project=project, order=20)

        response = client.post(
            self.reorder_url(project.pk),
            {"ordered_ids": [str(s3.pk), str(s1.pk), str(s2.pk)]},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        s1.refresh_from_db()
        s3.refresh_from_db()
        assert s3.order < s1.order
