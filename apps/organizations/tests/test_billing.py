"""
Tests for the Stripe billing views and webhooks.
"""
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework import status

from apps.accounts.tests.factories import MembershipFactory
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


def _org_client(authenticated_client, role="admin"):
    client, user = authenticated_client
    membership = MembershipFactory(user=user, role=role)
    org = membership.organization
    client.credentials(HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"])
    return client, user, org


@patch("apps.organizations.billing_views.stripe.checkout.Session.create")
@patch("apps.organizations.billing_views.get_or_create_stripe_customer")
def test_create_checkout_session(
    mock_get_customer, mock_checkout_create, authenticated_client, settings
):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    client, user, org = _org_client(authenticated_client, role="admin")

    mock_get_customer.return_value = "cus_123"
    mock_checkout_create.return_value = {"id": "cs_123", "url": "https://checkout.stripe.com/cs_123"}

    response = client.post(
        f"/api/v1/organizations/{org.slug}/billing/checkout/",
        {"price_id": "price_123"},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["url"] == "https://checkout.stripe.com/cs_123"
    mock_checkout_create.assert_called_once()


@patch("apps.organizations.billing_views.stripe.billing_portal.Session.create")
def test_create_portal_session(mock_portal_create, authenticated_client, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    client, user, org = _org_client(authenticated_client, role="admin")
    org.stripe_customer_id = "cus_123"
    org.save()

    mock_portal_create.return_value = {"url": "https://billing.stripe.com/p/session/123"}

    response = client.post(f"/api/v1/organizations/{org.slug}/billing/portal/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["url"] == "https://billing.stripe.com/p/session/123"
    mock_portal_create.assert_called_once()


def test_portal_fails_if_no_customer(authenticated_client, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    client, user, org = _org_client(authenticated_client, role="admin")
    # No stripe_customer_id

    response = client.post(f"/api/v1/organizations/{org.slug}/billing/portal/")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Subscribe first" in response.json()["detail"]


@patch("apps.organizations.billing_views.stripe.Webhook.construct_event")
@patch("apps.organizations.billing_views.stripe.Subscription.retrieve")
def test_webhook_checkout_completed(
    mock_sub_retrieve, mock_construct_event, api_client, settings, db
):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_123"
    settings.STRIPE_PRO_PRICE_ID = "price_pro"

    # Setup an org waiting for checkout
    org = MembershipFactory(role="admin").organization
    org.stripe_customer_id = "cus_123"
    org.save()

    # Mock the webhook event
    mock_construct_event.return_value = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "customer": "cus_123",
                "subscription": "sub_123",
            }
        }
    }

    # Mock fetching the subscription to get the price
    future_date = int((timezone.now() + timedelta(days=30)).timestamp())
    mock_sub_retrieve.return_value = {
        "items": {"data": [{"price": {"id": "price_pro"}}]},
        "current_period_end": future_date,
    }

    response = api_client.post(
        "/api/v1/billing/webhook/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=123,v1=sig"
    )
    assert response.status_code == status.HTTP_200_OK

    org.refresh_from_db()
    assert org.plan == "pro"
    assert org.stripe_subscription_id == "sub_123"
    assert org.subscription_status == Organization.SubscriptionStatus.ACTIVE
    assert org.current_period_end is not None


@patch("apps.organizations.billing_views.stripe.Webhook.construct_event")
def test_webhook_subscription_deleted(mock_construct_event, api_client, settings, db):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_123"

    org = MembershipFactory(role="admin").organization
    org.stripe_customer_id = "cus_123"
    org.plan = "pro"
    org.subscription_status = Organization.SubscriptionStatus.ACTIVE
    org.save()

    mock_construct_event.return_value = {
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "customer": "cus_123",
            }
        }
    }

    response = api_client.post(
        "/api/v1/billing/webhook/",
        data=json.dumps({}),
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=123,v1=sig"
    )
    assert response.status_code == status.HTTP_200_OK

    org.refresh_from_db()
    assert org.plan == "free"
    assert org.subscription_status == Organization.SubscriptionStatus.CANCELED
    assert org.stripe_subscription_id == ""
    assert org.current_period_end is None
