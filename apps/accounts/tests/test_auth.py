"""
Auth endpoint tests — register, login, refresh, logout, me, change-password.

pytest-django + factory_boy. No mocking needed for core auth.
"""
import pytest
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .factories import UserFactory

pytestmark = pytest.mark.django_db


class TestRegister:
    url = "/api/v1/auth/register/"

    def test_register_success(self, api_client):
        payload = {
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
        }
        response = api_client.post(self.url, payload)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "tokens" in data
        assert "access" in data["tokens"]
        assert "refresh" in data["tokens"]
        assert data["user"]["email"] == "newuser@example.com"

    def test_register_duplicate_email(self, api_client):
        UserFactory(email="existing@example.com")
        payload = {
            "email": "existing@example.com",
            "first_name": "Dupe",
            "last_name": "User",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
        }
        response = api_client.post(self.url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_password_mismatch(self, api_client):
        payload = {
            "email": "mismatch@example.com",
            "first_name": "Test",
            "last_name": "User",
            "password": "StrongPass123!",
            "password_confirm": "DifferentPass456!",
        }
        response = api_client.post(self.url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "password_confirm" in response.json().get("errors", {})

    def test_register_short_password(self, api_client):
        payload = {
            "email": "short@example.com",
            "first_name": "Short",
            "last_name": "Pass",
            "password": "abc",
            "password_confirm": "abc",
        }
        response = api_client.post(self.url, payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestLogin:
    url = "/api/v1/auth/login/"

    def test_login_success(self, api_client):
        UserFactory(email="login@example.com")
        response = api_client.post(
            self.url, {"email": "login@example.com", "password": "TestPass123!"}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access" in data
        assert "refresh" in data
        assert data["user"]["email"] == "login@example.com"

    def test_login_wrong_password(self, api_client):
        UserFactory(email="wrongpass@example.com")
        response = api_client.post(
            self.url, {"email": "wrongpass@example.com", "password": "WrongPassword!"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_nonexistent_user(self, api_client):
        response = api_client.post(
            self.url, {"email": "ghost@example.com", "password": "anything"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestTokenRefresh:
    url = "/api/v1/auth/token/refresh/"

    def test_refresh_success(self, api_client):
        user = UserFactory()
        refresh = RefreshToken.for_user(user)
        response = api_client.post(self.url, {"refresh": str(refresh)})
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.json()

    def test_refresh_invalid_token(self, api_client):
        response = api_client.post(self.url, {"refresh": "notavalidtoken"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestLogout:
    url = "/api/v1/auth/logout/"

    def test_logout_success(self, authenticated_client):
        client, user = authenticated_client
        refresh = RefreshToken.for_user(user)
        response = client.post(self.url, {"refresh": str(refresh)})
        assert response.status_code == status.HTTP_200_OK

    def test_logout_requires_auth(self, api_client):
        response = api_client.post(self.url, {"refresh": "token"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_logout_blacklists_token(self, authenticated_client):
        client, user = authenticated_client
        refresh = RefreshToken.for_user(user)
        refresh_str = str(refresh)

        # First logout
        client.post(self.url, {"refresh": refresh_str})

        # Using the same token again should fail
        response = client.post("/api/v1/auth/token/refresh/", {"refresh": refresh_str})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestMe:
    url = "/api/v1/auth/me/"

    def test_get_profile(self, authenticated_client):
        client, user = authenticated_client
        response = client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == user.email
        assert "memberships" in data

    def test_update_profile(self, authenticated_client):
        client, user = authenticated_client
        response = client.patch(self.url, {"first_name": "Updated", "bio": "Hello!"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["first_name"] == "Updated"

    def test_me_requires_auth(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestChangePassword:
    url = "/api/v1/auth/change-password/"

    def test_change_password_success(self, authenticated_client):
        client, user = authenticated_client
        response = client.post(
            self.url,
            {
                "old_password": "TestPass123!",
                "new_password": "NewStrongPass456!",
                "new_password_confirm": "NewStrongPass456!",
            },
        )
        assert response.status_code == status.HTTP_200_OK
        assert "tokens" in response.json()

    def test_change_password_wrong_old(self, authenticated_client):
        client, user = authenticated_client
        response = client.post(
            self.url,
            {
                "old_password": "WrongOld123!",
                "new_password": "NewStrongPass456!",
                "new_password_confirm": "NewStrongPass456!",
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
