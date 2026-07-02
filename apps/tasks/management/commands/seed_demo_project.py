"""
python manage.py seed_demo_project [--large-project] [--reset]

Seeds one large, realistic showcase project ("Platform Relaunch Q1") into the
demo organization, with enough structure to fully populate the project
dashboard: Kanban columns, labels, ~150 tasks with assignees/dates/progress,
and a backfilled activity trail feeding the velocity chart and activity feed.

Design notes:
  - Tasks/assignments/labels are bulk_create'd THROUGH the ORM's through
    tables, deliberately skipping post_save / m2m signals: no notification
    spam, no WebSocket broadcasts, and full control over the activity trail.
  - ActivityLog rows are bulk-created and then re-dated via bulk_update,
    because created_at is auto_now_add and would otherwise be "now".
  - A fixed RNG seed keeps reseeds reproducible (same shape, same avatars).
  - --reset deletes ONLY this demo project (cascades to its statuses, labels,
    tasks and logs) — other orgs/projects are never touched.
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.organizations.models import MemberRole, Membership, Organization
from apps.tasks.models import (
    ActivityLog,
    Label,
    Priority,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
)

User = get_user_model()

ORG_NAME = "TaskForge Demo"
ORG_SLUG = "taskforge-demo"
PROJECT_NAME = "Platform Relaunch Q1"
PASSWORD = "TaskForge2024!"
ADMIN_EMAIL = "admin@taskforge.dev"

DEMO_USERS = [
    ("olivia.rhodes@taskforge.dev", "Olivia", "Rhodes"),
    ("marcus.chen@taskforge.dev", "Marcus", "Chen"),
    ("priya.natarajan@taskforge.dev", "Priya", "Natarajan"),
    ("daniel.okafor@taskforge.dev", "Daniel", "Okafor"),
    ("sofia.marino@taskforge.dev", "Sofia", "Marino"),
    ("jonas.weber@taskforge.dev", "Jonas", "Weber"),
    ("amara.haddad@taskforge.dev", "Amara", "Haddad"),
    ("lucas.ferreira@taskforge.dev", "Lucas", "Ferreira"),
]

# (name, color, is_terminal)
STATUS_SPECS = [
    ("Backlog",     "#64748b", False),
    ("To-Do",       "#f59e0b", False),
    ("In Progress", "#3b82f6", False),
    ("In Review",   "#a855f7", False),
    ("Done",        "#22c55e", True),
]

LABEL_SPECS = [
    ("Editorial",  "#f97316"),
    ("Tech",       "#3b82f6"),
    ("Design",     "#ec4899"),
    ("Marketing",  "#84cc16"),
    ("Critical",   "#ef4444"),
    ("High",       "#f59e0b"),
    ("Medium",     "#38bdf8"),
]

# Titles repeat across columns on purpose — that's how real boards look.
TITLE_POOL = [
    "Rewrite UX Copy",
    "Migrate CMS Plugins",
    "Audit Editorial Guidelines",
    "Finalize CMS Plugin",
    "Test New CMS API",
    "Redesign Onboarding Flow",
    "Refactor Auth Middleware",
    "Ship Newsletter Templates",
    "Benchmark Search Index",
    "Update Brand Assets",
    "Polish Mobile Navigation",
    "Draft Launch Announcement",
    "Fix Payment Webhooks",
    "Harden Rate Limiting",
    "Localize Landing Pages",
    "Optimize Image Pipeline",
    "Review Accessibility Pass",
    "Instrument Analytics Events",
    "Clean Up Feature Flags",
    "Prototype Command Palette",
]

DESCRIPTION_POOL = [
    "Scoped during the relaunch planning workshop. See the linked brief for "
    "acceptance criteria and rollout constraints.",
    "Part of the Q1 platform relaunch track. Coordinate with the owning squad "
    "before merging anything user-facing.",
    "Follow-up from the last stakeholder review. Keep the change behind a "
    "feature flag until sign-off.",
    "Needs a short design review before implementation starts. Timebox the "
    "first pass to two days.",
    "",
]

# Column distribution: (status_name, large_count, small_count)
COLUMN_PLAN = [
    ("Backlog",     30, 10),
    ("To-Do",       55, 18),
    ("In Progress", 20,  7),
    ("In Review",   15,  5),
    ("Done",        30, 10),
]


class Command(BaseCommand):
    help = (
        "Seeds the large 'Platform Relaunch Q1' demo project with tasks, "
        "assignees, labels and a backfilled activity trail."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--large-project",
            action="store_true",
            help="Seed the full ~150-task showcase board (default is ~50 tasks).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete and recreate just this demo project (other data untouched).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(20260101)  # noqa: S311 — deterministic demo data, not crypto
        today = timezone.localdate()
        now = timezone.now()

        # ── Admin + org (reuses what `manage.py seed` creates) ────────────
        admin_user, created = User.objects.get_or_create(
            email=ADMIN_EMAIL,
            defaults={
                "first_name": "Demo",
                "last_name": "Admin",
                "is_verified": True,
                "is_staff": True,
            },
        )
        if created:
            admin_user.set_password(PASSWORD)
            admin_user.save()
        if not admin_user.avatar_url:
            admin_user.avatar_url = f"https://i.pravatar.cc/150?u={ADMIN_EMAIL}"
            admin_user.save(update_fields=["avatar_url"])

        org, _ = Organization.objects.get_or_create(
            slug=ORG_SLUG,
            defaults={
                "name": ORG_NAME,
                "owner": admin_user,
                "description": "Demo organization for TaskForge development & testing.",
            },
        )
        Membership.objects.get_or_create(
            user=admin_user, organization=org, defaults={"role": MemberRole.ADMIN},
        )

        # ── Demo team (deterministic pravatar avatars) ────────────────────
        team = [admin_user]
        for email, first, last in DEMO_USERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "is_verified": True,
                },
            )
            if created:
                user.set_password(PASSWORD)
            user.avatar_url = f"https://i.pravatar.cc/150?u={email}"
            user.save()
            Membership.objects.get_or_create(
                user=user,
                organization=org,
                defaults={"role": MemberRole.MEMBER, "invited_by": admin_user},
            )
            team.append(user)
        self.stdout.write(f"  [+] Team ready: {len(team)} members")

        # ── Project (reset or bail if it already exists) ──────────────────
        existing = Project.objects.filter(
            organization=org, name=PROJECT_NAME, is_deleted=False,
        ).first()
        if existing:
            if not options["reset"]:
                self.stdout.write(self.style.WARNING(
                    f'  [=] "{PROJECT_NAME}" already exists — pass --reset to recreate it.'
                ))
                return
            self.stdout.write(self.style.WARNING(f'  [-] Deleting existing "{PROJECT_NAME}"…'))
            existing.delete()

        project = Project.objects.create(
            name=PROJECT_NAME,
            description=(
                "Company-wide platform relaunch: new CMS, refreshed brand, "
                "editorial migration and marketing site rebuild."
            ),
            organization=org,
            owner=admin_user,
            status=ProjectStatus.IN_PROGRESS,
            priority=Priority.HIGH,
            due_date=today + timedelta(days=120),
        )

        statuses = {}
        for i, (name, color, is_terminal) in enumerate(STATUS_SPECS):
            statuses[name] = TaskStatus.objects.create(
                project=project, name=name, color=color,
                order=i * 10, is_terminal=is_terminal,
            )
        labels = {
            name: Label.objects.create(project=project, name=name, color=color)
            for name, color in LABEL_SPECS
        }
        self.stdout.write(
            f"  [+] Project created with {len(statuses)} columns, {len(labels)} labels"
        )

        # ── Tasks (bulk_create — signals intentionally skipped) ───────────
        large = options["large_project"]
        tasks = []
        reference = 0
        for status_name, large_count, small_count in COLUMN_PLAN:
            column = statuses[status_name]
            count = large_count if large else small_count
            for i in range(count):
                reference += 1
                if status_name == "Done":
                    due_offset = rng.randint(-56, 10)
                else:
                    due_offset = rng.randint(-42, 240)
                due = today + timedelta(days=due_offset)
                start = due - timedelta(days=rng.randint(5, 30))
                if status_name == "In Progress":
                    progress = rng.randint(10, 90)
                elif status_name == "Done":
                    progress = 100
                else:
                    progress = 0
                tasks.append(Task(
                    title=rng.choice(TITLE_POOL),
                    description=rng.choice(DESCRIPTION_POOL),
                    project=project,
                    status=column,
                    priority=rng.choices(
                        [Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.URGENT],
                        weights=[18, 42, 28, 12],
                    )[0],
                    reference=reference,
                    start_date=start,
                    due_date=due,
                    progress_percent=progress,
                    order=(i + 1) * 1000,
                ))
        Task.objects.bulk_create(tasks)

        AssigneeLink = Task.assignees.through
        LabelLink = Task.labels.through
        assignee_links, label_links = [], []
        for task in tasks:
            for user in rng.sample(team, k=rng.randint(1, 3)):
                assignee_links.append(AssigneeLink(task_id=task.id, user_id=user.id))
            for label in rng.sample(list(labels.values()), k=rng.randint(1, 2)):
                label_links.append(LabelLink(task_id=task.id, label_id=label.id))
        AssigneeLink.objects.bulk_create(assignee_links, ignore_conflicts=True)
        LabelLink.objects.bulk_create(label_links, ignore_conflicts=True)
        self.stdout.write(
            f"  [+] {len(tasks)} tasks seeded "
            f"({len(assignee_links)} assignments, {len(label_links)} label links)"
        )

        # ── Activity trail backfill ───────────────────────────────────────
        # status_changed→Done entries spread over the past 8 weeks feed the
        # velocity chart; the rest lands within 30 days for the feed.
        logs, timestamps = [], []

        def add_log(task, actor, verb, old_value, new_value, days_ago_max, days_ago_min=0):
            logs.append(ActivityLog(
                task=task, actor=actor, verb=verb,
                old_value=old_value, new_value=new_value,
            ))
            timestamps.append(now - timedelta(
                days=rng.randint(days_ago_min, days_ago_max),
                hours=rng.randint(0, 23),
                minutes=rng.randint(0, 59),
            ))

        done_status = statuses["Done"]
        review_status = statuses["In Review"]
        for task in tasks:
            add_log(task, rng.choice(team), "created", None,
                    {"title": task.title}, days_ago_max=60, days_ago_min=7)
            if task.status_id == done_status.id:
                add_log(task, rng.choice(team), "status_changed",
                        {"value": str(review_status.id)},
                        {"value": str(done_status.id)},
                        days_ago_max=55)

        for task in rng.sample(tasks, k=min(45, len(tasks))):
            kind = rng.choice(["assignees", "priority", "due_date", "status"])
            actor = rng.choice(team)
            if kind == "assignees":
                add_log(task, actor, "assignees_changed", None,
                        {"added": [rng.choice(team).email]}, days_ago_max=30)
            elif kind == "priority":
                add_log(task, actor, "priority_changed",
                        {"value": "medium"}, {"value": task.priority}, days_ago_max=30)
            elif kind == "due_date":
                add_log(task, actor, "due_date_changed",
                        {"value": None},
                        {"value": task.due_date.isoformat() if task.due_date else None},
                        days_ago_max=30)
            else:
                add_log(task, actor, "status_changed",
                        {"value": str(statuses["To-Do"].id)},
                        {"value": str(task.status_id)}, days_ago_max=30)

        created_logs = ActivityLog.objects.bulk_create(logs)
        for log, ts in zip(created_logs, timestamps, strict=False):
            log.created_at = ts
        ActivityLog.objects.bulk_update(created_logs, ["created_at"], batch_size=500)
        self.stdout.write(f"  [+] {len(created_logs)} activity log entries backfilled")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f'[OK] "{PROJECT_NAME}" seeded.'))
        self.stdout.write("")
        self.stdout.write(f"    Login:    {ADMIN_EMAIL} / {PASSWORD}")
        self.stdout.write(f"    Org slug: {ORG_SLUG}")
        self.stdout.write(f"    Board:    /orgs/{ORG_SLUG}/projects/{project.id}/board")
