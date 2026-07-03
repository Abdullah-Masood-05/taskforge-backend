"""
Project dashboard endpoint tests — timeline, analytics, activity feed,
export and import (round-trip).
"""
import io
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

from apps.accounts.tests.factories import MembershipFactory, UserFactory
from apps.tasks.models import ActivityLog, Project, Task

from .factories import LabelFactory, ProjectFactory, TaskFactory, TaskStatusFactory

pytestmark = pytest.mark.django_db


def _setup(authenticated_client, role="member"):
    client, user = authenticated_client
    membership = MembershipFactory(user=user, role=role)
    org = membership.organization
    project = ProjectFactory(organization=org, owner=user)
    return client, user, org, project


class TestProjectTimeline:
    def url(self, project_pk):
        return f"/api/v1/projects/{project_pk}/timeline/"

    def test_only_fully_dated_tasks_appear_sorted(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        s = TaskStatusFactory(project=project, is_terminal=False)
        today = timezone.localdate()

        late = TaskFactory(
            project=project, status=s,
            start_date=today + timedelta(days=5), due_date=today + timedelta(days=9),
        )
        early = TaskFactory(
            project=project, status=s,
            start_date=today, due_date=today + timedelta(days=3),
            assignees=[user],
        )
        TaskFactory(project=project, status=s)  # undated → excluded
        TaskFactory(project=project, status=s, due_date=today)  # no start → excluded

        response = client.get(self.url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [item["id"] for item in data] == [str(early.pk), str(late.pk)]

        first = data[0]
        assert first["start_date"] == today.isoformat()
        assert first["end_date"] == (today + timedelta(days=3)).isoformat()
        assert first["status"]["name"] == s.name
        assert first["status"]["is_terminal"] is False
        assert [a["email"] for a in first["assignees"]] == [user.email]

    def test_timeline_scoped_to_project(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        other = ProjectFactory(organization=org, owner=user)
        today = timezone.localdate()
        TaskFactory(
            project=other, status=TaskStatusFactory(project=other),
            start_date=today, due_date=today + timedelta(days=1),
        )

        response = client.get(self.url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []


class TestProjectAnalytics:
    def url(self, project_pk):
        return f"/api/v1/projects/{project_pk}/analytics/"

    def test_velocity_and_distribution(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        backlog = TaskStatusFactory(project=project, is_terminal=False)
        done = TaskStatusFactory(project=project, is_terminal=True)
        today = timezone.localdate()

        # planned this week: one task due today
        planned = TaskFactory(
            project=project, status=backlog, priority="high", due_date=today
        )
        # completed this week: a status_changed log into the terminal column
        moved = TaskFactory(project=project, status=done, priority="urgent")
        ActivityLog.objects.create(
            task=moved, actor=user, verb="status_changed",
            new_value={"value": str(done.pk)},
        )
        TaskFactory(project=project, status=backlog, priority="low")

        response = client.get(self.url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        velocity = data["velocity"]
        assert len(velocity) == 8
        this_week = velocity[-1]
        assert this_week["completed_count"] == 1
        assert this_week["planned_count"] == 1
        # earlier weeks stay empty
        assert all(w["completed_count"] == 0 for w in velocity[:-1])

        dist = {d["priority"]: d for d in data["distribution"]}
        assert set(dist) == {"urgent", "high", "medium", "low"}
        assert dist["urgent"]["count"] == 1
        assert dist["high"]["count"] == 1
        assert dist["low"]["count"] == 1
        assert dist["medium"]["count"] == 0
        assert dist["medium"]["percent"] == 0.0
        assert planned.pk  # silence unused warning

    def test_empty_project_analytics(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)

        response = client.get(self.url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert all(w["completed_count"] == 0 and w["planned_count"] == 0
                   for w in data["velocity"])
        assert all(d["count"] == 0 and d["percent"] == 0.0
                   for d in data["distribution"])


class TestProjectActivity:
    def url(self, project_pk):
        return f"/api/v1/projects/{project_pk}/activity/"

    def test_feed_newest_first_with_messages(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        s = TaskStatusFactory(project=project, name="In Review")
        task = TaskFactory(project=project, status=s)
        ActivityLog.objects.all().delete()  # drop signal-generated noise

        older = ActivityLog.objects.create(
            task=task, actor=user, verb="created",
            new_value={"title": task.title},
        )
        ActivityLog.objects.create(
            task=task, actor=user, verb="status_changed",
            new_value={"value": str(s.pk)},
        )
        # created_at is auto_now_add; push the first entry firmly into the past
        ActivityLog.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(minutes=5)
        )

        response = client.get(self.url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        # newest first
        assert data[0]["verb"] == "status_changed"
        assert "moved to In Review" in data[0]["message"]
        assert data[1]["verb"] == "created"
        assert data[0]["actor"]["email"] == user.email
        assert data[0]["task"]["id"] == str(task.pk)

    def test_limit_is_clamped(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project, status=TaskStatusFactory(project=project))
        ActivityLog.objects.all().delete()  # drop signal-generated noise
        for _ in range(3):
            ActivityLog.objects.create(task=task, actor=user, verb="created")

        response = client.get(
            self.url(project.pk) + "?limit=2", HTTP_X_ORGANIZATION_SLUG=org.slug
        )
        assert len(response.json()) == 2

        # nonsense limit falls back to the default
        response = client.get(
            self.url(project.pk) + "?limit=abc", HTTP_X_ORGANIZATION_SLUG=org.slug
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 3

    def test_message_rendering_for_every_verb(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client)
        task = TaskFactory(project=project, status=TaskStatusFactory(project=project))
        ActivityLog.objects.all().delete()

        entries = [
            ("assignees_changed", {"added": ["Alice"]}, "assigned Alice"),
            ("assignees_changed", {"removed": ["Bob"]}, "removed Bob"),
            ("assignees_changed", {"cleared": True}, "cleared assignees"),
            ("assignees_changed", {}, "changed assignees"),
            ("priority_changed", {"value": "high"}, "priority to High"),
            ("title_changed", {"value": "New title"}, 'renamed'),
            ("due_date_changed", {"value": "2026-08-01"}, "due date to 2026-08-01"),
            ("start_date_changed", {"value": None}, "start date to —"),
            ("progress_changed", {"value": 40}, "progress to 40%"),
            ("label_added", {"value": "backend"}, "label added on"),
        ]
        for verb, new_value, _ in entries:
            ActivityLog.objects.create(task=task, actor=None, verb=verb, new_value=new_value)

        response = client.get(
            self.url(project.pk) + "?limit=100", HTTP_X_ORGANIZATION_SLUG=org.slug
        )
        assert response.status_code == status.HTTP_200_OK
        messages = " | ".join(item["message"] for item in response.json())
        for _, _, fragment in entries:
            assert fragment in messages
        # actor-less entries render as "Someone"
        assert "Someone" in messages


class TestProjectArchive:
    def test_archive_toggle(self, authenticated_client):
        client, user, org, project = _setup(authenticated_client, role="admin")
        url = f"/api/v1/projects/{project.pk}/archive/"

        response = client.post(url, HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["archived"] is True

        response = client.post(url, HTTP_X_ORGANIZATION_SLUG=org.slug)
        assert response.json()["archived"] is False


class TestProjectExportImport:
    def export_url(self, project_pk):
        return f"/api/v1/projects/{project_pk}/export/"

    IMPORT_URL = "/api/v1/projects/import/"

    def _build_project(self, org, user):
        project = ProjectFactory(
            organization=org, owner=user, name="Template Alpha"
        )
        todo = TaskStatusFactory(project=project, name="To-Do", is_terminal=False)
        done = TaskStatusFactory(project=project, name="Done", is_terminal=True)
        label = LabelFactory(project=project, name="backend")
        assignee = UserFactory(email="teammate@example.com")
        MembershipFactory(user=assignee, organization=org)
        today = timezone.localdate()
        TaskFactory(
            project=project, status=todo, title="Ship the gateway",
            priority="high", start_date=today, due_date=today + timedelta(days=7),
            assignees=[assignee],
        ).labels.set([label])
        TaskFactory(project=project, status=done, title="Kickoff", priority="low")
        return project

    def test_export_payload_shape(self, authenticated_client):
        client, user, org, _ = _setup(authenticated_client)
        project = self._build_project(org, user)

        response = client.get(
            self.export_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug
        )
        assert response.status_code == status.HTTP_200_OK
        assert "attachment" in response["Content-Disposition"]

        payload = json.loads(response.content)
        assert payload["format"] == "taskforge.project"
        assert payload["project"]["name"] == "Template Alpha"
        assert [s["name"] for s in payload["statuses"]] == ["To-Do", "Done"]
        assert payload["labels"] == [{"name": "backend", "color": "#f59e0b"}]
        by_title = {t["title"]: t for t in payload["tasks"]}
        assert by_title["Ship the gateway"]["assignees"] == ["teammate@example.com"]
        assert by_title["Ship the gateway"]["labels"] == ["backend"]
        assert by_title["Kickoff"]["status"] == "Done"

    def test_import_round_trip(self, authenticated_client):
        client, user, org, _ = _setup(authenticated_client)
        project = self._build_project(org, user)
        exported = client.get(
            self.export_url(project.pk), HTTP_X_ORGANIZATION_SLUG=org.slug
        ).content

        upload = io.BytesIO(exported)
        upload.name = "template-alpha.json"
        response = client.post(
            self.IMPORT_URL, {"file": upload},
            HTTP_X_ORGANIZATION_SLUG=org.slug, format="multipart",
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["imported"] == {
            "statuses": 2, "labels": 1, "tasks": 2, "users_created": 0
        }

        clone = Project.objects.get(pk=body["project"]["id"])
        assert clone.pk != project.pk
        assert clone.name == "Template Alpha"
        titles = set(
            Task.objects.filter(project=clone).values_list("title", flat=True)
        )
        assert titles == {"Ship the gateway", "Kickoff"}
        shipped = Task.objects.get(project=clone, title="Ship the gateway")
        assert [u.email for u in shipped.assignees.all()] == ["teammate@example.com"]
        assert [lb.name for lb in shipped.labels.all()] == ["backend"]
        assert shipped.status.name == "To-Do"

    def test_import_creates_unknown_assignees(self, authenticated_client):
        client, user, org, _ = _setup(authenticated_client)
        payload = {
            "format": "taskforge.project",
            "version": 1,
            "project": {"name": "Imported Board"},
            "statuses": [{"name": "To-Do", "order": 0, "is_terminal": False}],
            "tasks": [
                {
                    "title": "Onboard the new hire",
                    "status": "To-Do",
                    "assignees": ["newcomer@example.com"],
                }
            ],
        }
        upload = io.BytesIO(json.dumps(payload).encode())
        upload.name = "board.json"

        response = client.post(
            self.IMPORT_URL, {"file": upload},
            HTTP_X_ORGANIZATION_SLUG=org.slug, format="multipart",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["imported"]["users_created"] == 1
        assert org.memberships.filter(user__email="newcomer@example.com").exists()

    def test_import_rejects_missing_file(self, authenticated_client):
        client, user, org, _ = _setup(authenticated_client)
        response = client.post(
            self.IMPORT_URL, {}, HTTP_X_ORGANIZATION_SLUG=org.slug, format="multipart"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_import_rejects_invalid_json(self, authenticated_client):
        client, user, org, _ = _setup(authenticated_client)
        upload = io.BytesIO(b"this is not json {")
        upload.name = "broken.json"
        response = client.post(
            self.IMPORT_URL, {"file": upload},
            HTTP_X_ORGANIZATION_SLUG=org.slug, format="multipart",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not valid JSON" in response.json()["detail"]
