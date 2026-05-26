"""
Root URL configuration for TaskForge.

dj-rest-auth is wired ONLY for the social login adapter bridge
(Google OAuth2 callback). All JWT auth endpoints are our own custom views
so we retain full control over token responses.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

api_v1_patterns = [
    # ── Auth (custom JWT views — full control over responses) ────────────
    path("auth/", include("apps.accounts.urls")),

    # ── Social auth adapter bridge (allauth → dj-rest-auth)
    # ONLY the social-login callback endpoint; NOT the JWT token views.
    path("auth/social/", include("dj_rest_auth.registration.urls")),

    # ── Organizations + membership ────────────────────────────────────────
    path("organizations/", include("apps.organizations.urls")),

    # ── Core utilities ────────────────────────────────────────────────────
    path("", include("apps.core.urls")),

    # ── OpenAPI schema + interactive docs ─────────────────────────────────
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
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
