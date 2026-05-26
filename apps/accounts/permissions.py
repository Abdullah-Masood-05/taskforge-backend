"""
Custom DRF permission classes for org-level role enforcement.

These are used on every org-scoped endpoint. The middleware
(CurrentOrgMiddleware) must have already attached request.org
before these are evaluated.

Hierarchy:  OrgAdmin > OrgMember > OrgViewer
"""
from rest_framework.permissions import BasePermission, IsAuthenticated
from apps.organizations.models import Membership, MemberRole


class IsOrgMember(IsAuthenticated):
    """
    Passes if the authenticated user is ANY member of request.org.
    Covers admin, member, and viewer roles.
    """

    message = "You are not a member of this organization."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        org = getattr(request, "org", None)
        if org is None:
            return False
        return Membership.objects.filter(
            user=request.user,
            organization=org,
        ).exists()


class IsOrgAdmin(IsAuthenticated):
    """
    Passes only for organization admins.
    Required for destructive operations: delete org, remove members,
    change billing plan.
    """

    message = "You must be an organization admin to perform this action."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        org = getattr(request, "org", None)
        if org is None:
            return False
        return Membership.objects.filter(
            user=request.user,
            organization=org,
            role=MemberRole.ADMIN,
        ).exists()


class IsOrgAdminOrReadOnly(IsAuthenticated):
    """
    Read-only for members/viewers; write access only for admins.
    Pattern: GET/HEAD/OPTIONS always pass (for any member),
    mutating methods require admin role.
    """

    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
    message = "Only organization admins can modify this resource."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        org = getattr(request, "org", None)
        if org is None:
            return False

        membership_qs = Membership.objects.filter(
            user=request.user, organization=org
        )
        if not membership_qs.exists():
            return False

        if request.method in self.SAFE_METHODS:
            return True

        return membership_qs.filter(role=MemberRole.ADMIN).exists()


class IsOrgViewer(IsAuthenticated):
    """
    Minimum permission: user must be at least a viewer.
    Equivalent to IsOrgMember — kept separate for semantic clarity.
    """

    message = "You must have at least viewer access to this organization."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        org = getattr(request, "org", None)
        if org is None:
            return False
        return Membership.objects.filter(
            user=request.user, organization=org
        ).exists()


class IsSelfOrAdmin(IsAuthenticated):
    """
    Object-level permission: passes if request.user == obj (own profile)
    or if the user is an org admin.
    """

    message = "You can only modify your own profile."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.user == obj:
            return True
        org = getattr(request, "org", None)
        if org is None:
            return False
        return Membership.objects.filter(
            user=request.user,
            organization=org,
            role=MemberRole.ADMIN,
        ).exists()
