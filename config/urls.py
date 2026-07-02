"""
Root URL configuration for TaskForge.

dj-rest-auth is wired ONLY for the social login adapter bridge
(Google OAuth2 callback). All JWT auth endpoints are our own custom views
so we retain full control over token responses.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.organizations.billing_views import StripeWebhookView

api_v1_patterns = [
    # ── Auth (custom JWT views — full control over responses) ────────────
    path("auth/", include("apps.accounts.urls")),

    # ── Social auth adapter bridge (allauth → dj-rest-auth)
    # ONLY the social-login callback endpoint; NOT the JWT token views.
    path("auth/social/", include("dj_rest_auth.registration.urls")),

    # ── Organizations + membership ────────────────────────────────────────────
    path("organizations/", include("apps.organizations.urls")),

    # ── Tasks + projects ──────────────────────────────────────────────────────
    path("", include("apps.tasks.urls")),

    # ── Notifications + attachments + reports ───────────────────────
    path("", include("apps.notifications.urls")),

    # ── Stripe billing webhook (global — no org slug; resolves org via customer ID) ──
    path(
        "billing/webhook/",
        StripeWebhookView.as_view(),
        name="stripe-webhook",
    ),

    # ── Core utilities ────────────────────────────────────────────────────
    path("", include("apps.core.urls")),

    # ── OpenAPI schema + interactive docs ─────────────────────────────────
    # url_name must be namespaced: these patterns are included under "api_v1".
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api_v1:schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api_v1:schema"), name="redoc"),
]

from apps.core.views import health_check  # noqa: E402

urlpatterns = [
    path("admin/", admin.site.urls),
    # Root-level alias matching Render's healthCheckPath (/health/).
    path("health/", health_check, name="health-check-root"),
    path("api/v1/", include((api_v1_patterns, "api_v1"))),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # Debug toolbar
    try:
        import debug_toolbar
        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass

    # Silk profiler
    urlpatterns += [path("silk/", include("silk.urls", namespace="silk"))]
