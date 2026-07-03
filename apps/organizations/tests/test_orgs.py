"""
Organization and membership permission tests.
"""
import pytest
from rest_framework import status

from .factories import MembershipFactory, OrganizationFactory, UserFactory

pytestmark = pytest.mark.django_db


class TestOrganizationCRUD:
    list_url = "/api/v1/organizations/"

    def detail_url(self, slug):
        return f"/api/v1/organizations/{slug}/"

    def test_create_org(self, authenticated_client):
        client, user = authenticated_client
        response = client.post(self.list_url, {"name": "My New Org"})
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "My New Org"
        assert "slug" in data
        # Creator should automatically be admin
        from apps.organizations.models import MemberRole, Membership
        assert Membership.objects.filter(
            user=user, organization__slug=data["slug"], role=MemberRole.ADMIN
        ).exists()

    def test_list_own_orgs_only(self, authenticated_client):
        client, user = authenticated_client
        # Create an org the user belongs to
        MembershipFactory(user=user)
        # Create an org the user does NOT belong to
        OrganizationFactory()

        response = client.get(self.list_url)
        assert response.status_code == status.HTTP_200_OK
        # Should only see the one they belong to
        assert response.json()["count"] == 1

    def test_retrieve_org_as_member(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user)
        org = membership.organization

        response = client.get(self.detail_url(org.slug))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["slug"] == org.slug

    def test_update_org_as_admin(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="admin")
        org = membership.organization

        response = client.patch(
            self.detail_url(org.slug),
            {"description": "Updated description"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_200_OK

    def test_update_org_as_member_forbidden(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="member")
        org = membership.organization

        response = client.patch(
            self.detail_url(org.slug),
            {"description": "Should fail"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_delete_org_soft_deletes(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="admin")
        org = membership.organization

        response = client.delete(
            self.detail_url(org.slug),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        org.refresh_from_db()
        assert org.is_deleted is True

    def test_non_member_cannot_access_org(self, authenticated_client):
        client, user = authenticated_client
        other_org = OrganizationFactory()

        response = client.get(self.detail_url(other_org.slug))
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestMemberManagement:
    def members_url(self, slug):
        return f"/api/v1/organizations/{slug}/members/"

    def member_detail_url(self, slug, pk):
        return f"/api/v1/organizations/{slug}/members/{pk}/"

    def test_list_members_as_member(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="member")
        org = membership.organization

        response = client.get(
            self.members_url(org.slug),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_200_OK

    def test_viewer_cannot_list_if_not_member(self, authenticated_client):
        client, user = authenticated_client
        other_org = OrganizationFactory()

        response = client.get(
            self.members_url(other_org.slug),
            HTTP_X_ORGANIZATION_SLUG=other_org.slug,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_invite_existing_user(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="admin")
        org = membership.organization
        new_user = UserFactory()

        response = client.post(
            self.members_url(org.slug),
            {"email": new_user.email, "role": "member"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_member_cannot_invite(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="member")
        org = membership.organization
        new_user = UserFactory()

        response = client.post(
            self.members_url(org.slug),
            {"email": new_user.email, "role": "member"},
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_remove_last_admin(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="admin")
        org = membership.organization
        # user is the only admin
        response = client.delete(
            self.member_detail_url(org.slug, str(membership.id)),
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestMiddlewareOrgResolution:
    def test_org_resolved_from_header(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="member")
        org = membership.organization

        response = client.get(
            f"/api/v1/organizations/{org.slug}/",
            HTTP_X_ORGANIZATION_SLUG=org.slug,
        )
        assert response.status_code == status.HTTP_200_OK

    def test_org_resolved_from_url_slug(self, authenticated_client):
        client, user = authenticated_client
        membership = MembershipFactory(user=user, role="member")
        org = membership.organization

        # No header — URL slug should resolve the org
        response = client.get(f"/api/v1/organizations/{org.slug}/")
        assert response.status_code == status.HTTP_200_OK

    def test_missing_org_slug_on_protected_endpoint(self, authenticated_client):
        client, user = authenticated_client
        other_org = OrganizationFactory()

        # No membership and no matching slug
        response = client.get(f"/api/v1/organizations/{other_org.slug}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
