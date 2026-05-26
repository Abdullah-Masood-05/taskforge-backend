"""
Root conftest.py — shared fixtures for all tests.

Fixtures defined here are available to every test without importing.
"""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.tests.factories import UserFactory


@pytest.fixture
def api_client():
    """Unauthenticated DRF test client."""
    return APIClient()


@pytest.fixture
def authenticated_client():
    """
    Returns (client, user) — client is pre-authenticated via JWT Bearer token.
    Usage:
        def test_something(authenticated_client):
            client, user = authenticated_client
            response = client.get("/api/v1/auth/me/")
    """
    user = UserFactory()
    refresh = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client, user


@pytest.fixture
def admin_client():
    """Authenticated client whose user is a staff/superuser."""
    user = UserFactory(is_staff=True, is_superuser=True)
    refresh = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client, user
