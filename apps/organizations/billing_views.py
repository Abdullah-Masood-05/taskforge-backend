"""
Stripe billing views for the organizations app.

Four endpoints, all scoped to /api/v1/organizations/{slug}/billing/:

  POST billing/checkout/   — create a Stripe Checkout session (subscription flow)
  POST billing/portal/     — create a Stripe Customer Portal session (manage billing)
  POST billing/webhook/    — receive Stripe webhook events (CSRF-exempt, sig-verified)
  GET  billing/status/     — return the org's current billing state

Design notes:
  - The webhook view is @csrf_exempt and uses AllowAny permission because Stripe
    cannot send a CSRF token. Security comes from Stripe signature verification
    (STRIPE_WEBHOOK_SECRET). Missing this causes silent 403s — see note in connect().
  - All other views require IsOrgAdmin so only org admins can change billing.
  - Augmenting Organization (no separate Subscription model) is the chosen design;
    see apps/organizations/models.py for the rationale.
"""
from datetime import UTC

import stripe
import structlog
from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsOrgAdmin
from apps.organizations.billing import get_or_create_stripe_customer, plan_from_price_id
from apps.organizations.models import Organization

logger = structlog.get_logger(__name__)


def _get_org(slug, user):
    """Resolve org from slug, raise 404 if not found."""
    from django.shortcuts import get_object_or_404
    return get_object_or_404(Organization, slug=slug, is_deleted=False)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Checkout Session
# ─────────────────────────────────────────────────────────────────────────────

class CreateCheckoutSessionView(APIView):
    """
    POST /api/v1/organizations/{slug}/billing/checkout/

    Body: { "price_id": "price_xxx" }

    Creates a Stripe Checkout session in subscription mode and returns the
    hosted URL. The frontend redirects the user to that URL.

    success_url and cancel_url redirect back to the billing page.
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def post(self, request, slug):
        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Billing is not configured."}, status=503)

        org = _get_org(slug, request.user)
        price_id = request.data.get("price_id")
        if not price_id:
            return Response({"detail": "price_id is required."}, status=400)

        stripe.api_key = settings.STRIPE_SECRET_KEY
        frontend_base = settings.FRONTEND_URL.rstrip("/")

        customer_id = get_or_create_stripe_customer(org, request.user)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{frontend_base}/orgs/{slug}/billing?checkout=success",
            cancel_url=f"{frontend_base}/orgs/{slug}/pricing",
            metadata={"org_id": str(org.id), "org_slug": slug},
        )
        logger.info(
            "stripe_checkout_created",
            org_id=str(org.id),
            session_id=session["id"],
        )
        return Response({"url": session["url"]})


# ─────────────────────────────────────────────────────────────────────────────
# 2. Customer Portal Session
# ─────────────────────────────────────────────────────────────────────────────

class BillingPortalView(APIView):
    """
    POST /api/v1/organizations/{slug}/billing/portal/

    Creates a Stripe Customer Portal session so the user can manage their
    subscription, update payment methods, and download invoices.
    Requires an existing Stripe customer (org must have subscribed once).
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def post(self, request, slug):
        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Billing is not configured."}, status=503)

        org = _get_org(slug, request.user)
        if not org.stripe_customer_id:
            return Response(
                {"detail": "No billing account found. Subscribe first."},
                status=400,
            )

        stripe.api_key = settings.STRIPE_SECRET_KEY
        frontend_base = settings.FRONTEND_URL.rstrip("/")

        portal = stripe.billing_portal.Session.create(
            customer=org.stripe_customer_id,
            return_url=f"{frontend_base}/orgs/{slug}/billing",
        )
        logger.info("stripe_portal_opened", org_id=str(org.id))
        return Response({"url": portal["url"]})


# ─────────────────────────────────────────────────────────────────────────────
# 3. Stripe Webhook
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    """
    POST /api/v1/billing/webhook/

    Receives and processes Stripe webhook events.

    Security: CSRF exempt (Stripe cannot send CSRF tokens) but all events are
    verified with stripe.Webhook.construct_event() using STRIPE_WEBHOOK_SECRET.
    Without this verification, any actor could send arbitrary events.

    Handled events:
      checkout.session.completed        → persist subscription_id, upgrade plan
      customer.subscription.updated     → sync plan, status, period_end
      customer.subscription.deleted     → downgrade to free, clear subscription
      invoice.payment_failed            → set status=past_due
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response(status=200)  # Ignore if unconfigured

        stripe.api_key = settings.STRIPE_SECRET_KEY
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except stripe.error.SignatureVerificationError:
            logger.warning("stripe_webhook_invalid_signature")
            return Response({"detail": "Invalid signature."}, status=400)
        except Exception as exc:
            logger.error("stripe_webhook_parse_error", error=str(exc))
            return Response({"detail": "Webhook parse error."}, status=400)

        event_type = event["type"]
        data = event["data"]["object"]

        handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.payment_failed": self._handle_payment_failed,
        }
        handler = handlers.get(event_type)
        if handler:
            try:
                handler(data)
            except Exception as exc:
                logger.error(
                    "stripe_webhook_handler_error",
                    event_type=event_type,
                    error=str(exc),
                )
                # Return 200 anyway so Stripe doesn't retry indefinitely
        else:
            logger.debug("stripe_webhook_unhandled", event_type=event_type)

        return Response(status=200)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _get_org_by_customer(self, customer_id):
        try:
            return Organization.objects.get(stripe_customer_id=customer_id, is_deleted=False)
        except Organization.DoesNotExist:
            logger.warning("stripe_org_not_found", customer_id=customer_id)
            return None

    def _handle_checkout_completed(self, session):
        """checkout.session.completed — subscription flow finished."""
        if session.get("mode") != "subscription":
            return
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        org = self._get_org_by_customer(customer_id)
        if not org:
            return

        # Fetch subscription to determine the price/plan
        stripe.api_key = settings.STRIPE_SECRET_KEY
        sub = stripe.Subscription.retrieve(subscription_id)
        price_id = sub["items"]["data"][0]["price"]["id"]

        org.stripe_subscription_id = subscription_id
        org.plan = plan_from_price_id(price_id)
        org.subscription_status = Organization.SubscriptionStatus.ACTIVE
        org.current_period_end = timezone.datetime.fromtimestamp(
            sub["current_period_end"], tz=UTC
        )
        org.save(update_fields=[
            "stripe_subscription_id", "plan",
            "subscription_status", "current_period_end",
        ])
        logger.info(
            "stripe_checkout_completed",
            org_id=str(org.id),
            plan=org.plan,
            subscription_id=subscription_id,
        )

    def _handle_subscription_updated(self, subscription):
        """customer.subscription.updated — plan change, renewal, trial end."""
        customer_id = subscription.get("customer")
        org = self._get_org_by_customer(customer_id)
        if not org:
            return

        price_id = subscription["items"]["data"][0]["price"]["id"]
        status = subscription["status"]

        org.plan = plan_from_price_id(price_id)
        org.subscription_status = status
        org.current_period_end = timezone.datetime.fromtimestamp(
            subscription["current_period_end"], tz=UTC
        )
        org.save(update_fields=["plan", "subscription_status", "current_period_end"])
        logger.info(
            "stripe_subscription_updated",
            org_id=str(org.id),
            plan=org.plan,
            status=status,
        )

    def _handle_subscription_deleted(self, subscription):
        """customer.subscription.deleted — subscription cancelled."""
        customer_id = subscription.get("customer")
        org = self._get_org_by_customer(customer_id)
        if not org:
            return

        org.plan = "free"
        org.subscription_status = Organization.SubscriptionStatus.CANCELED
        org.stripe_subscription_id = ""
        org.current_period_end = None
        org.save(update_fields=[
            "plan", "subscription_status",
            "stripe_subscription_id", "current_period_end",
        ])
        logger.info("stripe_subscription_deleted", org_id=str(org.id))

    def _handle_payment_failed(self, invoice):
        """invoice.payment_failed — mark org as past_due."""
        customer_id = invoice.get("customer")
        org = self._get_org_by_customer(customer_id)
        if not org:
            return

        org.subscription_status = Organization.SubscriptionStatus.PAST_DUE
        org.save(update_fields=["subscription_status"])
        logger.warning("stripe_payment_failed", org_id=str(org.id))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Billing Status
# ─────────────────────────────────────────────────────────────────────────────

class BillingStatusView(APIView):
    """
    GET /api/v1/organizations/{slug}/billing/status/

    Returns the org's current billing state for the frontend dashboard.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, slug):
        org = _get_org(slug, request.user)
        return Response({
            "plan": org.plan,
            "subscription_status": org.subscription_status,
            "current_period_end": (
                org.current_period_end.isoformat() if org.current_period_end else None
            ),
            "has_billing_account": bool(org.stripe_customer_id),
        })
