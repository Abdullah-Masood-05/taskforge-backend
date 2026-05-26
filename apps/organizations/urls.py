"""
URL patterns for the organizations app.

Nested routes:
  /organizations/                        — org CRUD
  /organizations/{slug}/members/         — member management
  /organizations/{slug}/members/{id}/    — specific member
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MemberViewSet, OrganizationViewSet

router = DefaultRouter()
router.register(r"", OrganizationViewSet, basename="organization")

urlpatterns = [
    path("", include(router.urls)),
    # Nested member routes — explicitly defined for clarity
    path(
        "<slug:slug>/members/",
        MemberViewSet.as_view({"get": "list", "post": "create"}),
        name="org-members-list",
    ),
    path(
        "<slug:slug>/members/<uuid:pk>/",
        MemberViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="org-members-detail",
    ),
    path(
        "<slug:slug>/members/pending-invitations/",
        MemberViewSet.as_view({"get": "pending_invitations"}),
        name="org-members-invitations",
    ),
]
