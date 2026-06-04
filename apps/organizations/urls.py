"""
URL patterns for the organizations app.

Nested routes:
  /organizations/                        — org CRUD
  /organizations/{slug}/members/         — member management
  /organizations/{slug}/members/{id}/    — specific member
  /organizations/{slug}/billing/checkout/   — Stripe checkout session
  /organizations/{slug}/billing/portal/     — Stripe customer portal
  /organizations/{slug}/billing/status/     — current billing state
  /billing/webhook/                         — Stripe webhook (global, no slug)
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MemberViewSet, OrganizationViewSet
from .billing_views import (
    BillingPortalView,
    BillingStatusView,
    CreateCheckoutSessionView,
    StripeWebhookView,
)

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
    # Billing routes (admin-only except status)
    path(
        "<slug:slug>/billing/checkout/",
        CreateCheckoutSessionView.as_view(),
        name="org-billing-checkout",
    ),
    path(
        "<slug:slug>/billing/portal/",
        BillingPortalView.as_view(),
        name="org-billing-portal",
    ),
    path(
        "<slug:slug>/billing/status/",
        BillingStatusView.as_view(),
        name="org-billing-status",
    ),
]
