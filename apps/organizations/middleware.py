"""
CurrentOrgMiddleware — resolves the current organization from the request.

Resolution order (first match wins):
  1. URL kwargs: if the view has a `slug` kwarg (e.g. /api/v1/organizations/{slug}/)
     we resolve the org from there.
  2. X-Organization-Slug header: explicit header sent by the frontend.
  3. No org found: request.org is set to None (non-org endpoints still work).

Using both methods means frontend clients don't need to set the header
on every request if the URL already contains the slug.
"""
import structlog
from django.utils.deprecation import MiddlewareMixin

from .models import Organization

logger = structlog.get_logger(__name__)


class CurrentOrgMiddleware(MiddlewareMixin):
    """
    Attaches the resolved Organization object to every request as `request.org`.

    Designed to be idempotent — if no org can be resolved, request.org = None
    and the endpoint proceeds normally (useful for auth endpoints that have
    no org context).
    """

    HEADER_NAME = "HTTP_X_ORGANIZATION_SLUG"

    def process_request(self, request):
        # Default to no org context
        request.org = None
        request.org_membership = None

        slug = self._resolve_slug(request)
        if not slug:
            return  # No org context — fine for public/auth endpoints

        try:
            org = (
                Organization.objects
                .select_related("owner")
                .get(slug__iexact=slug, is_deleted=False)
            )
            request.org = org

            # Eagerly fetch the current user's membership if authenticated.
            # This is used by permission classes without an extra DB hit.
            if hasattr(request, "user") and request.user.is_authenticated:
                try:
                    from .models import Membership
                    request.org_membership = Membership.objects.get(
                        user=request.user,
                        organization=org,
                    )
                except Membership.DoesNotExist:
                    request.org_membership = None

        except Organization.DoesNotExist:
            logger.warning("org_not_found", slug=slug)
            # Don't raise 404 here — let the view decide how to handle a
            # missing org. Permission classes will block access appropriately.
            request.org = None

    def _resolve_slug(self, request) -> str | None:
        """
        Try URL kwargs first, then fall back to the header.
        URL kwargs require the URL resolver to have already run, which it
        has by the time middleware sees the request in Django's flow.
        """
        # 1. URL kwarg resolution (e.g. /api/v1/organizations/{slug}/)
        try:
            from django.urls import resolve
            match = resolve(request.path_info)
            slug = match.kwargs.get("slug")
            if slug:
                return slug
        except Exception:  # noqa: S110
            pass

        # 2. Header fallback
        slug = request.META.get(self.HEADER_NAME, "").strip()
        return slug if slug else None
