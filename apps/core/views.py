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
    GET /api/v1/health/            liveness: the process is up (no I/O)
    GET /api/v1/health/?deep=1     readiness: also checks Postgres and Redis

    Platform probes and the keep-alive pinger hit the plain URL every few
    seconds/minutes. That must not touch the database: Neon's free plan
    suspends idle compute after 5 minutes and caps compute hours per month,
    so a probe that runs SELECT 1 would keep the database awake around the
    clock and exhaust the quota. Use ?deep=1 for a full dependency check.
    """
    if request.query_params.get("deep") not in ("1", "true", "yes"):
        return Response({"status": "ok"})

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
        redis_url = settings.REDIS_URL if hasattr(settings, "REDIS_URL") else             settings.CACHES["default"]["LOCATION"]
        r = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=2)
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
