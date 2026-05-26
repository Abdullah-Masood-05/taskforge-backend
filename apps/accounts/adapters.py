"""
Allauth adapters — bridge between django-allauth and our custom User model.

dj-rest-auth is used ONLY to expose the social login callback URL.
All JWT token operations use our own custom views.
"""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings


class AccountAdapter(DefaultAccountAdapter):
    """Customise allauth behaviour for email-based registration."""

    def is_open_for_signup(self, request):
        # Can be toggled via settings for invite-only mode
        return getattr(settings, "ACCOUNT_ALLOW_SIGNUPS", True)

    def get_email_confirmation_url(self, request, emailconfirmation):
        """Point verification links at the frontend, not the Django backend."""
        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
        key = emailconfirmation.key
        return f"{frontend_url}/auth/verify-email/{key}/"


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Customise allauth social account behaviour."""

    def is_open_for_signup(self, request, sociallogin):
        return getattr(settings, "ACCOUNT_ALLOW_SIGNUPS", True)

    def populate_user(self, request, sociallogin, data):
        """Populate user fields from social provider data."""
        user = super().populate_user(request, sociallogin, data)
        # Ensure first_name / last_name are always populated from Google profile
        if sociallogin.account.provider == "google":
            extra = sociallogin.account.extra_data
            user.first_name = user.first_name or extra.get("given_name", "")
            user.last_name = user.last_name or extra.get("family_name", "")
            user.is_verified = True  # Google emails are pre-verified
        return user
