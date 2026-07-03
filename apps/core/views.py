"""
Core app views: health check endpoint.
"""
import redis
from django.conf import settings
from django.db import connection
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])  # platform health probes fire every few seconds — never throttle
def health_check(request):
    """
    GET /api/v1/health/

    Returns 200 if both DB and Redis are reachable, 503 otherwise.
    Used by load balancers, Docker healthchecks, and uptime monitors.
    """
    checks = {}
    overall_status = "ok"

    # ── Database ────────────────────────────────────────────────────────
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        overall_status = "degraded"

    # ── Redis ────────────────────────────────────────────────────────────
    try:
        redis_url = settings.REDIS_URL if hasattr(settings, "REDIS_URL") else \
            settings.CACHES["default"]["LOCATION"]
        r = redis.from_url(redis_url, socket_connect_timeout=1)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        overall_status = "degraded"

    http_status = 200 if overall_status == "ok" else 503
    return Response(
        {"status": overall_status, "checks": checks},
        status=http_status,
    )
