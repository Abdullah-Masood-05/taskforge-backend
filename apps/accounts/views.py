"""
Custom JWT auth views.

These are our own views — we do NOT use dj-rest-auth JWT views.
This gives us full control over token response shape, error messages,
and throttling behaviour.
"""
import structlog
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import status, generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserSerializer,
    ChangePasswordSerializer,
)

logger = structlog.get_logger(__name__)
User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/

    Creates a new user. Returns JWT token pair + user data on success
    so the frontend can log in immediately after registration.
    """

    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = "auth"

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Issue tokens immediately — no separate login step needed
        refresh = RefreshToken.for_user(user)
        logger.info("user_registered", user_id=str(user.id), email=user.email)

        return Response(
            {
                "message": _("Registration successful."),
                "user": UserSerializer(user, context={"request": request}).data,
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/

    Returns access + refresh tokens alongside user data.
    Uses our CustomTokenObtainPairSerializer.
    Axes brute-force protection is applied via middleware.
    """

    permission_classes = [AllowAny]
    serializer_class = CustomTokenObtainPairSerializer
    throttle_scope = "auth"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        user = serializer.user
        logger.info("user_login", user_id=str(user.id), email=user.email)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class TokenRefreshView(TokenRefreshView):
    """
    POST /api/v1/auth/token/refresh/

    Standard simplejwt refresh view — re-exported for our URL namespace.
    ROTATE_REFRESH_TOKENS=True means a new refresh token is also returned.
    """
    pass  # Inherits all behaviour from simplejwt


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/

    Blacklists the provided refresh token, invalidating the session.
    The access token will expire naturally (15-minute lifetime).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"detail": _("Refresh token is required.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            logger.info("user_logout", user_id=str(request.user.id))
        except TokenError:
            return Response(
                {"detail": _("Token is invalid or already blacklisted.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": _("Successfully logged out.")}, status=status.HTTP_200_OK)


class MeView(generics.RetrieveUpdateAPIView):
    """
    GET  /api/v1/auth/me/   — retrieve current user profile
    PUT  /api/v1/auth/me/   — update profile (name, bio, timezone, avatar)
    """

    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/

    Validates old password before setting a new one. Issues a new token
    pair after success so the frontend doesn't need a separate login.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"old_password": [_("Wrong password.")]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        # Re-issue tokens (old tokens are implicitly invalidated by password change)
        refresh = RefreshToken.for_user(user)
        logger.info("user_password_changed", user_id=str(user.id))

        return Response(
            {
                "detail": _("Password changed successfully."),
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
            },
            status=status.HTTP_200_OK,
        )
