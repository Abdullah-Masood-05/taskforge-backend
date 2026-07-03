"""
Organization ViewSets and membership management views.

Design note:
- OrganizationViewSet uses slug as the URL lookup field.
- MemberViewSet is nested under /organizations/{slug}/members/.
- Permission classes from apps.accounts.permissions enforce RBAC.
"""
from datetime import timedelta

import structlog
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsOrgAdmin, IsOrgMember

from .models import Invitation, MemberRole, Membership, Organization
from .serializers import (
    InvitationSerializer,
    InviteMemberSerializer,
    MembershipSerializer,
    OrganizationListSerializer,
    OrganizationSerializer,
    UpdateMemberRoleSerializer,
)

logger = structlog.get_logger(__name__)
User = get_user_model()

INVITATION_EXPIRY_DAYS = 7


class OrganizationViewSet(viewsets.ModelViewSet):
    """
    CRUD for organizations.

    GET    /organizations/          — list orgs the current user belongs to
    POST   /organizations/          — create a new org
    GET    /organizations/{slug}/   — retrieve org detail
    PUT    /organizations/{slug}/   — update org (admin only)
    PATCH  /organizations/{slug}/   — partial update (admin only)
    DELETE /organizations/{slug}/   — soft-delete org (admin only)
    """

    lookup_field = "slug"
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        """Return only orgs the user is a member of."""
        return (
            Organization.objects.filter(
                memberships__user=self.request.user,
                is_deleted=False,
            )
            .select_related("owner")
            .prefetch_related("memberships")
            .distinct()
        )

    def get_serializer_class(self):
        if self.action == "list":
            return OrganizationListSerializer
        return OrganizationSerializer

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy"):
            return [IsOrgAdmin()]
        return [IsAuthenticated()]

    def perform_destroy(self, instance):
        instance.soft_delete()
        logger.info(
            "org_deleted",
            org_id=str(instance.id),
            org_slug=instance.slug,
            deleted_by=str(self.request.user.id),
        )


class MemberViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Member management nested under /organizations/{slug}/members/.

    GET    /organizations/{slug}/members/       — list members
    POST   /organizations/{slug}/members/       — invite a new member
    PATCH  /organizations/{slug}/members/{id}/  — change member role
    DELETE /organizations/{slug}/members/{id}/  — remove member
    """

    serializer_class = MembershipSerializer

    def _get_org(self):
        # request.org is already set by CurrentOrgMiddleware
        if self.request.org:
            return self.request.org
        return get_object_or_404(Organization, slug=self.kwargs["slug"], is_deleted=False)

    def get_queryset(self):
        org = self._get_org()
        return (
            Membership.objects.filter(organization=org)
            .select_related("user", "invited_by")
            .order_by("joined_at")
        )

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsOrgAdmin()]
        return [IsOrgMember()]

    def create(self, request, *args, **kwargs):
        """Invite a user by email. Creates Invitation record + sends email."""
        org = self._get_org()
        serializer = InviteMemberSerializer(
            data=request.data, context={"org": org, "request": request}
        )
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        role = serializer.validated_data["role"]

        # If user already exists, add them directly; otherwise send invite
        try:
            user = User.objects.get(email__iexact=email)
            membership = Membership.objects.create(
                user=user,
                organization=org,
                role=role,
                invited_by=request.user,
            )
            logger.info(
                "member_added_directly",
                org_id=str(org.id),
                user_id=str(user.id),
                role=role,
            )
            return Response(
                MembershipSerializer(membership).data,
                status=status.HTTP_201_CREATED,
            )

        except User.DoesNotExist:
            # Create a pending invitation
            invitation = Invitation.objects.create(
                organization=org,
                email=email,
                role=role,
                invited_by=request.user,
                expires_at=timezone.now() + timedelta(days=INVITATION_EXPIRY_DAYS),
            )
            # TODO: Phase 3 — send invite email via Celery task
            logger.info(
                "invitation_created",
                org_id=str(org.id),
                email=email,
                invitation_id=str(invitation.id),
            )
            return Response(
                InvitationSerializer(invitation).data,
                status=status.HTTP_201_CREATED,
            )

    def partial_update(self, request, *args, **kwargs):
        """Change a member's role."""
        membership = self.get_object()
        org = self._get_org()

        # Prevent demoting the last admin
        if (
            membership.role == MemberRole.ADMIN
            and org.memberships.filter(role=MemberRole.ADMIN).count() == 1
        ):
            return Response(
                {"detail": _("Cannot change the role of the last admin.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UpdateMemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership.role = serializer.validated_data["role"]
        membership.save(update_fields=["role"])
        return Response(MembershipSerializer(membership).data)

    def destroy(self, request, *args, **kwargs):
        """Remove a member. Prevents removing yourself if last admin."""
        membership = self.get_object()
        org = self._get_org()

        if (
            membership.role == MemberRole.ADMIN
            and org.memberships.filter(role=MemberRole.ADMIN).count() == 1
        ):
            return Response(
                {"detail": _("Cannot remove the last admin of an organization.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership.delete()
        logger.info(
            "member_removed",
            org_id=str(org.id),
            removed_user_id=str(membership.user.id),
            removed_by=str(request.user.id),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="pending-invitations")
    def pending_invitations(self, request, *args, **kwargs):
        """GET /organizations/{slug}/members/pending-invitations/"""
        org = self._get_org()
        invitations = Invitation.objects.filter(
            organization=org, status=Invitation.STATUS_PENDING
        )
        return Response(InvitationSerializer(invitations, many=True).data)
