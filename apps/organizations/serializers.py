"""
Serializers for the organizations app.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Invitation, Membership, MemberRole, Organization

User = get_user_model()


class OrganizationSerializer(serializers.ModelSerializer):
    """Full org detail — used for create/retrieve/update."""

    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "logo",
            "website",
            "owner_email",
            "plan",
            "member_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "plan", "owner_email", "created_at", "updated_at"]

    def get_member_count(self, obj) -> int:
        return obj.memberships.count()

    def create(self, validated_data):
        request = self.context["request"]
        org = Organization.objects.create(owner=request.user, **validated_data)
        # Creator automatically becomes admin
        Membership.objects.create(
            user=request.user,
            organization=org,
            role=MemberRole.ADMIN,
        )
        return org


class OrganizationListSerializer(serializers.ModelSerializer):
    """Compact serializer for list endpoints."""

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "plan", "created_at"]
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    """Full membership detail including user info."""

    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    user_avatar = serializers.ImageField(source="user.avatar", read_only=True)
    invited_by_email = serializers.EmailField(source="invited_by.email", read_only=True)

    class Meta:
        model = Membership
        fields = [
            "id",
            "user_email",
            "user_full_name",
            "user_avatar",
            "role",
            "invited_by_email",
            "joined_at",
        ]
        read_only_fields = ["id", "user_email", "user_full_name", "invited_by_email", "joined_at"]


class MembershipSummarySerializer(serializers.ModelSerializer):
    """
    Lightweight serializer embedded in UserSerializer.get_memberships.
    Shows only org slug + role — avoids deep nesting.
    """

    org_name = serializers.CharField(source="organization.name", read_only=True)
    org_slug = serializers.CharField(source="organization.slug", read_only=True)

    class Meta:
        model = Membership
        fields = ["org_name", "org_slug", "role", "joined_at"]


class InviteMemberSerializer(serializers.Serializer):
    """Request body for POST /organizations/{slug}/members/ (invite)."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=MemberRole.choices, default=MemberRole.MEMBER)

    def validate_email(self, value: str) -> str:
        return value.lower()

    def validate(self, attrs):
        org = self.context["org"]

        # Check if already a member
        if Membership.objects.filter(
            user__email__iexact=attrs["email"],
            organization=org,
        ).exists():
            raise serializers.ValidationError(
                {"email": _("This user is already a member of the organization.")}
            )

        # Check for existing pending invite
        if Invitation.objects.filter(
            email__iexact=attrs["email"],
            organization=org,
            status=Invitation.STATUS_PENDING,
            expires_at__gt=timezone.now(),
        ).exists():
            raise serializers.ValidationError(
                {"email": _("An invitation has already been sent to this email.")}
            )

        return attrs


class UpdateMemberRoleSerializer(serializers.Serializer):
    """Request body for PATCH /organizations/{slug}/members/{id}/."""

    role = serializers.ChoiceField(choices=MemberRole.choices)


class InvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "status", "expires_at", "created_at"]
        read_only_fields = fields
