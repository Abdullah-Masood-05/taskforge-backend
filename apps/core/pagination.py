"""
Shared pagination classes.

CreatedAtCursorPagination — cursor-based pagination for high-churn, append-only
feeds (notifications, activity log). Cursor pagination is preferred over
page-number pagination for these because:
  - New rows are constantly inserted at the head, which shifts page-number
    offsets and causes items to be skipped or repeated between requests.
  - It scales to large tables without expensive COUNT/OFFSET queries.

Response shape: { "next": <url|null>, "previous": <url|null>, "results": [...] }
(There is intentionally no "count" — cursor pagination cannot cheaply provide one.)
"""
from rest_framework.pagination import CursorPagination


class CreatedAtCursorPagination(CursorPagination):
    """Newest-first cursor pagination keyed on the `created_at` timestamp."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"
    cursor_query_param = "cursor"
