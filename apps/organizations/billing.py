"""
Stripe customer and subscription helpers for the organizations app.

All Stripe API calls live here so billing_views.py stays thin (just HTTP in/out).
"""
import stripe
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


def _stripe():
    """Return stripe module with the secret key set. Raises if unconfigured."""
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError(
            "STRIPE_SECRET_KEY is not configured. "
            "Set it in .env to enable billing features."
        )
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def get_or_create_stripe_customer(org, user):
    """
    Return the Stripe customer ID for the org, creating one if needed.

    The customer ID is persisted on org.stripe_customer_id so Stripe is
    only called once per org lifetime.
    """
    s = _stripe()

    if org.stripe_customer_id:
        return org.stripe_customer_id

    customer = s.Customer.create(
        email=user.email,
        name=org.name,
        metadata={
            "org_id": str(org.id),
            "org_slug": org.slug,
        },
    )
    org.stripe_customer_id = customer["id"]
    org.save(update_fields=["stripe_customer_id"])
    logger.info(
        "stripe_customer_created",
        org_id=str(org.id),
        stripe_customer_id=customer["id"],
    )
    return customer["id"]


PLAN_FROM_PRICE = {
    settings.__class__.__dict__.get("STRIPE_PRO_PRICE_ID", ""): "pro",
    settings.__class__.__dict__.get("STRIPE_BUSINESS_PRICE_ID", ""): "business",
}


def plan_from_price_id(price_id: str) -> str:
    """Resolve a Stripe price ID to our internal plan name."""
    # Read at call time so settings are fully populated
    mapping = {
        settings.STRIPE_PRO_PRICE_ID: "pro",
        settings.STRIPE_BUSINESS_PRICE_ID: "business",
    }
    return mapping.get(price_id, "free")
