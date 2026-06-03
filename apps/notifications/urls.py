"""
URL patterns for the notifications app.

All routes are prefixed with /api/v1/ in config/urls.py.

Route map:
  /notifications/                        — list
  /notifications/unread-count/           — unread count
  /notifications/{id}/read/              — mark one read
  /notifications/mark-all-read/          — mark all read
  /tasks/{task_pk}/attachments/          — list
  /tasks/{task_pk}/attachments/upload/   — request presigned upload URL
  /tasks/{task_pk}/attachments/upload-local/ — dev multipart upload
  /tasks/{task_pk}/attachments/{id}/     — delete
  /reports/                              — create export job
  /reports/{id}/                         — poll status
  /reports/{id}/download/                — get download URL
"""
from django.urls import path

from .views import AttachmentViewSet, ExportJobViewSet, NotificationViewSet

# ── Notifications ─────────────────────────────────────────────────────────────
notification_list = NotificationViewSet.as_view({"get": "list"})
notification_unread = NotificationViewSet.as_view({"get": "unread_count"})
notification_read = NotificationViewSet.as_view({"post": "mark_read"})
notification_mark_all = NotificationViewSet.as_view({"post": "mark_all_read"})

# ── Attachments ───────────────────────────────────────────────────────────────
attachment_list = AttachmentViewSet.as_view({"get": "list"})
attachment_upload = AttachmentViewSet.as_view({"post": "request_upload"})
attachment_upload_local = AttachmentViewSet.as_view({"post": "upload_local"})
attachment_detail = AttachmentViewSet.as_view({"delete": "destroy"})

# ── Export Jobs ───────────────────────────────────────────────────────────────
export_list = ExportJobViewSet.as_view({"post": "create"})
export_detail = ExportJobViewSet.as_view({"get": "retrieve"})
export_download = ExportJobViewSet.as_view({"get": "download"})

urlpatterns = [
    # Notifications
    path("notifications/", notification_list, name="notification-list"),
    path("notifications/unread-count/", notification_unread, name="notification-unread-count"),
    path("notifications/mark-all-read/", notification_mark_all, name="notification-mark-all-read"),
    path("notifications/<uuid:pk>/read/", notification_read, name="notification-read"),

    # Attachments (nested under tasks)
    path(
        "tasks/<uuid:task_pk>/attachments/",
        attachment_list,
        name="task-attachment-list",
    ),
    path(
        "tasks/<uuid:task_pk>/attachments/upload/",
        attachment_upload,
        name="task-attachment-upload",
    ),
    path(
        "tasks/<uuid:task_pk>/attachments/upload-local/",
        attachment_upload_local,
        name="task-attachment-upload-local",
    ),
    path(
        "tasks/<uuid:task_pk>/attachments/<uuid:pk>/",
        attachment_detail,
        name="task-attachment-detail",
    ),

    # Export Jobs
    path("reports/", export_list, name="export-job-create"),
    path("reports/<uuid:pk>/", export_detail, name="export-job-detail"),
    path("reports/<uuid:pk>/download/", export_download, name="export-job-download"),
]
