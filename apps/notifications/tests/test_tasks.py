"""
Tests for Celery tasks — run synchronously via CELERY_TASK_ALWAYS_EAGER=True.
"""
import pytest
from django.core import mail

from apps.accounts.tests.factories import (
    MembershipFactory,
    OrganizationFactory,
    UserFactory,
)
from apps.notifications.models import ExportJob, Notification
from apps.notifications.tasks import (
    generate_project_report,
    send_daily_digest,
    send_task_assignment_email,
    send_welcome_email,
)
from apps.tasks.models import Project, Task, TaskStatus


# ─────────────────────────────────────────────────────────────
# Email tasks
# ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWelcomeEmail:
    def test_sends_welcome_email(self):
        user = UserFactory()
        mail.outbox.clear()

        send_welcome_email(str(user.id))

        assert len(mail.outbox) == 1
        assert user.email in mail.outbox[0].to
        assert "Welcome" in mail.outbox[0].subject

    def test_nonexistent_user_is_graceful(self):
        mail.outbox.clear()
        import uuid
        send_welcome_email(str(uuid.uuid4()))
        assert len(mail.outbox) == 0


@pytest.mark.django_db
class TestAssignmentEmail:
    def test_sends_assignment_email(self):
        owner = UserFactory()
        org = OrganizationFactory(owner=owner)
        MembershipFactory(user=owner, organization=org, role="admin")
        assignee = UserFactory()
        MembershipFactory(user=assignee, organization=org, role="member")

        project = Project.objects.create(name="P", organization=org, owner=owner)
        status_col = TaskStatus.objects.create(name="Todo", project=project, order=0)
        task = Task.objects.create(
            title="Fix bug",
            project=project,
            status=status_col,
            assignee=assignee,
        )

        mail.outbox.clear()
        send_task_assignment_email(str(task.id), str(assignee.id), str(owner.id))

        assert len(mail.outbox) == 1
        assert assignee.email in mail.outbox[0].to
        assert "assigned" in mail.outbox[0].subject.lower()

    def test_nonexistent_task_is_graceful(self):
        import uuid
        user = UserFactory()
        mail.outbox.clear()
        send_task_assignment_email(str(uuid.uuid4()), str(user.id))
        assert len(mail.outbox) == 0


@pytest.mark.django_db
class TestDailyDigest:
    def test_sends_digest_to_users_with_unread(self):
        from apps.notifications.tests.factories import NotificationFactory

        user1 = UserFactory()
        user2 = UserFactory()
        # Mark welcome notifications as read so we start with a clean slate
        Notification.objects.filter(recipient__in=[user1, user2]).update(is_read=True)

        # user1 gets 3 new unread notifications; user2 stays clean
        NotificationFactory.create_batch(3, recipient=user1, is_read=False)

        mail.outbox.clear()
        send_daily_digest()

        # Only check digest emails sent to our two test users; ignore others
        recipients_for_test_users = {
            msg.to[0]
            for msg in mail.outbox
            if msg.to[0] in {user1.email, user2.email}
        }
        assert user1.email in recipients_for_test_users
        assert user2.email not in recipients_for_test_users


# ─────────────────────────────────────────────────────────────
# PDF Report generation
# ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestReportGeneration:
    def test_generates_pdf_and_completes_job(self):
        import os
        from django.conf import settings

        owner = UserFactory()
        org = OrganizationFactory(owner=owner)
        MembershipFactory(user=owner, organization=org, role="admin")
        project = Project.objects.create(name="Report Project", organization=org, owner=owner)
        status_col = TaskStatus.objects.create(name="Done", project=project, order=0)
        Task.objects.create(title="Task A", project=project, status=status_col, assignee=owner)
        Task.objects.create(title="Task B", project=project, status=status_col)

        job = ExportJob.objects.create(
            organization=org,
            project=project,
            requested_by=owner,
            status=ExportJob.Status.PENDING,
        )

        # Run task synchronously (CELERY_TASK_ALWAYS_EAGER=True)
        generate_project_report(str(job.id))

        job.refresh_from_db()
        assert job.status == ExportJob.Status.COMPLETED
        assert job.file_key != ""
        assert job.completed_at is not None

        # In dev mode, the file should exist on the local filesystem
        if not settings.USE_S3:
            full_path = os.path.join(settings.MEDIA_ROOT, job.file_key)
            assert os.path.exists(full_path)
            assert os.path.getsize(full_path) > 0

    def test_export_job_api_create_and_poll(self):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        owner = UserFactory()
        org = OrganizationFactory(owner=owner)
        MembershipFactory(user=owner, organization=org, role="admin")
        project = Project.objects.create(name="API Report", organization=org, owner=owner)

        client = APIClient()
        token = RefreshToken.for_user(owner)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        client.defaults["HTTP_X_ORGANIZATION_SLUG"] = org.slug

        resp = client.post(
            "/api/v1/reports/",
            {"project_id": str(project.id)},
            format="json",
        )
        assert resp.status_code == 201
        job_id = resp.data["id"]

        # In eager mode, the task has already run; poll returns completed
        poll = client.get(f"/api/v1/reports/{job_id}/")
        assert poll.status_code == 200
        assert poll.data["status"] == ExportJob.Status.COMPLETED

        # Download endpoint returns a URL
        dl = client.get(f"/api/v1/reports/{job_id}/download/")
        assert dl.status_code == 200
        assert "download_url" in dl.data
