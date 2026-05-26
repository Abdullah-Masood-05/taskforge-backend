"""
Serializers for the accounts app.

CustomTokenObtainPairSerializer — enriches the JWT payload with user metadata.
RegisterSerializer — custom registration with first/last name.
UserSerializer — read/write profile serializer.
"""
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends simplejwt's base serializer to embed user data in the response.
    This is our own class — dj-rest-auth JWT views are NOT used.
    """

    def validate(self, attrs):
        data = super().validate(attrs)
        # Append user details alongside the token pair
        data["user"] = UserSerializer(self.user, context=self.context).data
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Extra claims embedded in the JWT payload itself
        token["email"] = user.email
        token["full_name"] = user.full_name
        token["is_verified"] = user.is_verified
        return token


class RegisterSerializer(serializers.ModelSerializer):
    """Registration serializer — creates a User with hashed password."""

    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        error_messages={"min_length": _("Password must be at least 8 characters.")},
    )
    password_confirm = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = [
            "email",
            "first_name",
            "last_name",
            "password",
            "password_confirm",
        ]

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(_("A user with this email already exists."))
        return value.lower()

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": _("Passwords do not match.")})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    """Read/write serializer for user profile. Password excluded."""

    full_name = serializers.CharField(read_only=True)
    memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "avatar",
            "bio",
            "timezone",
            "is_verified",
            "date_joined",
            "memberships",
        ]
        read_only_fields = ["id", "email", "is_verified", "date_joined"]

    def get_memberships(self, obj):
        """Return the user's org memberships (role per org)."""
        from apps.organizations.serializers import MembershipSummarySerializer
        memberships = obj.memberships.select_related("organization").filter(
            organization__is_deleted=False
        )
        return MembershipSummarySerializer(memberships, many=True).data


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, style={"input_type": "password"})
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
    )
    new_password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": _("New passwords do not match.")}
            )
        return attrs
