"""
Organization and Membership models — the heart of multi-tenancy.

Every resource in the system hangs off an Organization FK.
Membership binds a User to an Organization with a specific role.
"""
import uuid
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class MemberRole(models.TextChoices):
    ADMIN = "admin", _("Admin")
    MEMBER = "member", _("Member")
    VIEWER = "viewer", _("Viewer")


class Plan(models.TextChoices):
    FREE = "free", _("Free")
    PRO = "pro", _("Pro")
    BUSINESS = "business", _("Business")


class Organization(models.Model):
    """
    Top-level tenant. Every other model in the system FK's to this.

    Slug is the primary URL identifier — stable, human-readable, unique.
    Soft-delete: deleted orgs are flagged, not physically removed,
    so audit logs and billing records remain intact.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("name"), max_length=120)
    slug = models.SlugField(
        _("slug"),
        max_length=80,
        unique=True,
        db_index=True,
        help_text=_("Used in URLs and API calls. Letters, numbers and hyphens only."),
    )
    description = models.TextField(_("description"), blank=True, max_length=500)
    logo = models.ImageField(
        _("logo"), upload_to="org_logos/%Y/%m/", null=True, blank=True
    )
    website = models.URLField(_("website"), blank=True)

    # Ownership
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organizations",
        verbose_name=_("owner"),
    )

    # Billing
    plan = models.CharField(
        _("plan"), max_length=20, choices=Plan.choices, default=Plan.FREE, db_index=True
    )
    stripe_customer_id = models.CharField(
        _("Stripe customer ID"), max_length=120, blank=True, db_index=True
    )
    stripe_subscription_id = models.CharField(
        _("Stripe subscription ID"), max_length=120, blank=True
    )

    # Soft delete
    is_deleted = models.BooleanField(_("deleted"), default=False, db_index=True)
    deleted_at = models.DateTimeField(_("deleted at"), null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("organization")
        verbose_name_plural = _("organizations")
        ordering = ["-created_at"]
        # DB-level constraint: slug must be unique among non-deleted orgs
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(is_deleted=False),
                name="unique_active_org_slug",
            )
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def _generate_unique_slug(self) -> str:
        base_slug = slugify(self.name)[:70]
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])


class Membership(models.Model):
    """
    Many-to-many relationship between User and Organization, with role.

    A user can belong to multiple organizations with different roles.
    Unique constraint prevents duplicate memberships at the DB level.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("user"),
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("organization"),
    )
    role = models.CharField(
        _("role"),
        max_length=20,
        choices=MemberRole.choices,
        default=MemberRole.MEMBER,
        db_index=True,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invitations",
        verbose_name=_("invited by"),
    )
    joined_at = models.DateTimeField(_("joined at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("membership")
        verbose_name_plural = _("memberships")
        ordering = ["joined_at"]
        constraints = [
            # DB-level guarantee: one membership per (user, org) pair
            models.UniqueConstraint(
                fields=["user", "organization"],
                name="unique_user_org_membership",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "role"], name="membership_org_role_idx"),
            models.Index(fields=["user", "organization"], name="membership_user_org_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} → {self.organization.name} ({self.role})"


class Invitation(models.Model):
    """
    Pending invitation for a user who hasn't signed up yet.
    Accepted when the invitee registers and confirms the token.
    """

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, _("Pending")),
        (STATUS_ACCEPTED, _("Accepted")),
        (STATUS_EXPIRED, _("Expired")),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField(_("email"), db_index=True)
    role = models.CharField(_("role"), max_length=20, choices=MemberRole.choices, default=MemberRole.MEMBER)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="outgoing_invitations",
    )
    token = models.UUIDField(_("token"), default=uuid.uuid4, unique=True, db_index=True)
    status = models.CharField(_("status"), max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    expires_at = models.DateTimeField(_("expires at"))
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("invitation")
        verbose_name_plural = _("invitations")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invite {self.email} → {self.organization.name}"
