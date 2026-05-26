"""
URL patterns for the accounts app.
All JWT operations are handled by our own views.
"""
from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    TokenRefreshView,
    LogoutView,
    MeView,
    ChangePasswordView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
]
