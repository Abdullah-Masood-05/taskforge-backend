"""
python manage.py seed

Creates a complete demo dataset for local development and manual testing:
  - Demo admin user
  - Demo org with the admin as owner
  - Two additional members (member + viewer roles)

Run this after running migrations. Safe to run multiple times (idempotent).
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds the database with demo data for local development."

    # ── Demo data constants ─────────────────────────────────────────────
    ADMIN_EMAIL = "admin@taskforge.dev"
    ADMIN_PASSWORD = "TaskForge2024!"
    MEMBER_EMAIL = "alice@taskforge.dev"
    VIEWER_EMAIL = "bob@taskforge.dev"
    ORG_NAME = "TaskForge Demo"
    ORG_SLUG = "taskforge-demo"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo data before seeding.",
        )

    def handle(self, *args, **options):
        from apps.organizations.models import Invitation, Membership, MemberRole, Organization

        if options["reset"]:
            self.stdout.write(self.style.WARNING("Resetting demo data..."))
            User.objects.filter(email__in=[
                self.ADMIN_EMAIL, self.MEMBER_EMAIL, self.VIEWER_EMAIL
            ]).delete()
            Organization.objects.filter(slug=self.ORG_SLUG).delete()

        self.stdout.write(self.style.MIGRATE_HEADING("[Seed] Seeding TaskForge demo data..."))

        # ── Users ───────────────────────────────────────────────────────
        admin_user, created = User.objects.get_or_create(
            email=self.ADMIN_EMAIL,
            defaults={
                "first_name": "Demo",
                "last_name": "Admin",
                "is_verified": True,
                "is_staff": True,
            },
        )
        if created:
            admin_user.set_password(self.ADMIN_PASSWORD)
            admin_user.save()
            self.stdout.write(f"  [+] Created admin user: {self.ADMIN_EMAIL}")
        else:
            self.stdout.write(f"  [=] Admin user already exists: {self.ADMIN_EMAIL}")

        alice, created = User.objects.get_or_create(
            email=self.MEMBER_EMAIL,
            defaults={
                "first_name": "Alice",
                "last_name": "Member",
                "is_verified": True,
            },
        )
        if created:
            alice.set_password(self.ADMIN_PASSWORD)
            alice.save()
            self.stdout.write(f"  [+] Created member user: {self.MEMBER_EMAIL}")
        else:
            self.stdout.write(f"  [=] Member user already exists: {self.MEMBER_EMAIL}")

        bob, created = User.objects.get_or_create(
            email=self.VIEWER_EMAIL,
            defaults={
                "first_name": "Bob",
                "last_name": "Viewer",
                "is_verified": True,
            },
        )
        if created:
            bob.set_password(self.ADMIN_PASSWORD)
            bob.save()
            self.stdout.write(f"  [+] Created viewer user: {self.VIEWER_EMAIL}")
        else:
            self.stdout.write(f"  [=] Viewer user already exists: {self.VIEWER_EMAIL}")

        # ── Organization ─────────────────────────────────────────────────
        org, created = Organization.objects.get_or_create(
            slug=self.ORG_SLUG,
            defaults={
                "name": self.ORG_NAME,
                "owner": admin_user,
                "description": "Demo organization for TaskForge development & testing.",
            },
        )
        if created:
            self.stdout.write(f"  [+] Created organization: {self.ORG_NAME} (slug: {self.ORG_SLUG})")
        else:
            self.stdout.write(f"  [=] Organization already exists: {self.ORG_NAME}")

        # ── Memberships ─────────────────────────────────────────────────
        Membership.objects.get_or_create(
            user=admin_user,
            organization=org,
            defaults={"role": MemberRole.ADMIN},
        )
        Membership.objects.get_or_create(
            user=alice,
            organization=org,
            defaults={"role": MemberRole.MEMBER, "invited_by": admin_user},
        )
        Membership.objects.get_or_create(
            user=bob,
            organization=org,
            defaults={"role": MemberRole.VIEWER, "invited_by": admin_user},
        )
        self.stdout.write("  [+] Memberships configured (admin + member + viewer)")

        # ── Pending Invitation ────────────────────────────────────────────
        Invitation.objects.get_or_create(
            email="charlie@example.com",
            organization=org,
            defaults={
                "role": MemberRole.MEMBER,
                "invited_by": admin_user,
                "expires_at": timezone.now() + timedelta(days=7),
            },
        )
        self.stdout.write("  [+] Created 1 pending invitation (charlie@example.com)")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("[OK] Demo seed complete!"))
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("  Credentials (all share the same password):"))
        self.stdout.write(f"    Admin  -> {self.ADMIN_EMAIL}")
        self.stdout.write(f"    Member -> {self.MEMBER_EMAIL}")
        self.stdout.write(f"    Viewer -> {self.VIEWER_EMAIL}")
        self.stdout.write(f"    Password: {self.ADMIN_PASSWORD}")
        self.stdout.write(f"    Org slug: {self.ORG_SLUG}")
        self.stdout.write("")
        self.stdout.write("  API Docs: http://localhost:8000/api/v1/docs/")
        self.stdout.write("  Admin:    http://localhost:8000/admin/")
