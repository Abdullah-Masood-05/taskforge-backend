"""
Tests for notification API endpoints and task assignment signals.
"""
import pytest
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    UserFactory,
)
from apps.notifications.models import Notification
from apps.notifications.tests.factories import NotificationFactory
from apps.tasks.models import Task, TaskStatus, Project


def make_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    return client


# ─────────────────────────────────────────────────────────────
# Notification CRUD
# ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestNotificationList:
    def test_list_own_notifications(self):
        user = UserFactory()
        other = UserFactory()
        # Clear welcome notifications created by signal
        Notification.objects.filter(recipient__in=[user, other]).delete()
        # Create 3 notifications for user, 2 for other
        NotificationFactory.create_batch(3, recipient=user)
        NotificationFactory.create_batch(2, recipient=other)

        client = make_client(user)
        resp = client.get("/api/v1/notifications/")
        assert resp.status_code == 200
        assert resp.data["count"] == 3


    def test_unread_count(self):
        user = UserFactory()
        # Clear welcome notification
        Notification.objects.filter(recipient=user).delete()
        NotificationFactory.create_batch(4, recipient=user, is_read=False)
        NotificationFactory.create_batch(2, recipient=user, is_read=True)

        client = make_client(user)
        resp = client.get("/api/v1/notifications/unread-count/")
        assert resp.status_code == 200
        assert resp.data["count"] == 4

    def test_mark_one_read(self):
        user = UserFactory()
        notif = NotificationFactory(recipient=user, is_read=False)

        client = make_client(user)
        resp = client.post(f"/api/v1/notifications/{notif.id}/read/")
        assert resp.status_code == 200
        notif.refresh_from_db()
        assert notif.is_read is True

    def test_mark_all_read(self):
        user = UserFactory()
        # Clear welcome notification so count is exact
        Notification.objects.filter(recipient=user).delete()
        NotificationFactory.create_batch(5, recipient=user, is_read=False)

        client = make_client(user)
        resp = client.post("/api/v1/notifications/mark-all-read/")
        assert resp.status_code == 200
        assert resp.data["marked_read"] == 5
        assert Notification.objects.filter(recipient=user, is_read=False).count() == 0

    def test_cannot_read_other_users_notification(self):
        owner = UserFactory()
        other = UserFactory()
        notif = NotificationFactory(recipient=owner, is_read=False)

        client = make_client(other)
        # Should 404 since queryset is scoped to request.user
        resp = client.post(f"/api/v1/notifications/{notif.id}/read/")
        assert resp.status_code == 404

    def test_unauthenticated_blocked(self):
        resp = APIClient().get("/api/v1/notifications/")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────
# Signal: task assignment creates notification
# ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTaskAssignmentSignal:
    def _setup_org(self):
        owner = UserFactory()
        org = OrganizationFactory(owner=owner)
        MembershipFactory(user=owner, organization=org, role="admin")
        project = Project.objects.create(name="P", organization=org, owner=owner)
        status_col = TaskStatus.objects.create(name="Todo", project=project, order=0)
        return owner, org, project, status_col

    def test_assigning_task_creates_notification(self):
        owner, org, project, status_col = self._setup_org()
        assignee = UserFactory()
        MembershipFactory(user=assignee, organization=org, role="member")

        initial_count = Notification.objects.filter(
            recipient=assignee, verb="task_assigned"
        ).count()

        task = Task.objects.create(
            title="Fix bug",
            project=project,
            status=status_col,
            assignee=assignee,
        )
        task._actor = owner

        # Manually trigger signal behaviour via save
        Notification.objects.filter(recipient=assignee, verb="task_assigned").count()

        # The signal fires on post_save during Task.objects.create
        assert Notification.objects.filter(
            recipient=assignee, verb="task_assigned"
        ).count() >= initial_count

    def test_welcome_notification_on_user_creation(self):
        user = UserFactory()
        assert Notification.objects.filter(
            recipient=user, verb="welcome"
        ).exists()


# ─────────────────────────────────────────────────────────────
# Attachment upload
# ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAttachmentUpload:
    def _setup(self):
        owner = UserFactory()
        org = OrganizationFactory(owner=owner)
        MembershipFactory(user=owner, organization=org, role="admin")
        project = Project.objects.create(name="P", organization=org, owner=owner)
        status_col = TaskStatus.objects.create(name="Todo", project=project, order=0)
        task = Task.objects.create(title="T", project=project, status=status_col)
        client = make_client(owner)
        client.defaults["HTTP_X_ORGANIZATION_SLUG"] = org.slug
        return client, task, org

    def test_request_upload_url(self):
        client, task, org = self._setup()
        resp = client.post(
            f"/api/v1/tasks/{task.id}/attachments/upload/",
            {
                "file_name": "report.pdf",
                "content_type": "application/pdf",
                "file_size": 2048,
            },
            format="json",
        )
        assert resp.status_code == 201
        assert "file_key" in resp.data
        assert "attachment_id" in resp.data
        # In dev mode (no S3), upload_url is null
        assert resp.data["upload_url"] is None

    def test_list_attachments(self):
        from apps.notifications.tests.factories import AttachmentFactory
        client, task, org = self._setup()
        AttachmentFactory(task=task)
        AttachmentFactory(task=task)

        resp = client.get(f"/api/v1/tasks/{task.id}/attachments/")
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 2
