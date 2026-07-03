from django.contrib import admin

from .models import Invitation, Membership, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "plan", "owner", "is_deleted", "created_at"]
    list_filter = ["plan", "is_deleted"]
    search_fields = ["name", "slug", "owner__email"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organization", "role", "joined_at"]
    list_filter = ["role"]
    search_fields = ["user__email", "organization__name"]
    readonly_fields = ["id", "joined_at"]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["email", "organization", "role", "status", "expires_at", "created_at"]
    list_filter = ["status", "role"]
    search_fields = ["email", "organization__name"]
    readonly_fields = ["id", "token", "created_at"]
