"""
Views for the notifications app.

NotificationViewSet  — list, mark-as-read, mark-all-read, unread-count
AttachmentViewSet    — list, presigned upload, local upload (dev), delete
ExportJobViewSet     — create (triggers PDF task), retrieve (poll), download
"""

import structlog
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsOrgMember
from apps.core.pagination import CreatedAtCursorPagination
from apps.tasks.models import Attachment, Project, Task

from .models import ExportJob, Notification
from .serializers import (
    AttachmentSerializer,
    AttachmentUploadRequestSerializer,
    AttachmentUploadResponseSerializer,
    ExportJobCreateSerializer,
    ExportJobSerializer,
    NotificationSerializer,
)
from .storage import (
    delete_file,
    generate_file_key,
    generate_presigned_download_url,
    generate_presigned_upload_url,
    save_file_locally,
)
from .tasks import generate_project_report

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────

class NotificationViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    GET  /notifications/              — paginated list, newest first
    GET  /notifications/unread-count/ — { count: N }
    POST /notifications/{id}/read/    — mark one as read
    POST /notifications/mark-all-read/ — mark all as read
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CreatedAtCursorPagination

    def get_queryset(self):
        return (
            Notification.objects
            .filter(recipient=self.request.user)
            .select_related("actor", "target_ct")
            .order_by("-created_at")
        )

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
        return Response({"count": count})

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        return Response({"is_read": True})

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).update(is_read=True)
        return Response({"marked_read": updated})


# ─────────────────────────────────────────────────────────────
# Attachments
# ─────────────────────────────────────────────────────────────

class AttachmentViewSet(
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    GET    /tasks/{task_pk}/attachments/         — list attachments
    POST   /tasks/{task_pk}/attachments/upload/  — get presigned upload URL
    POST   /tasks/{task_pk}/attachments/upload-local/  — dev: upload file directly
    DELETE /tasks/{task_pk}/attachments/{id}/    — delete
    """
    serializer_class = AttachmentSerializer
    permission_classes = [IsOrgMember]

    def _get_task(self):
        return get_object_or_404(
            Task,
            pk=self.kwargs["task_pk"],
            project__organization=self.request.org,
            is_deleted=False,
        )

    def get_queryset(self):
        task = self._get_task()
        return (
            Attachment.objects
            .filter(task=task)
            .select_related("uploaded_by")
            .order_by("created_at")
        )

    @action(detail=False, methods=["post"], url_path="upload")
    def request_upload(self, request, task_pk=None):
        """
        Request a presigned URL to upload a file directly to S3 (or returns
        null upload_url in dev, directing client to use upload-local instead).
        Creates the Attachment record immediately so the client has an ID.
        """
        task = self._get_task()
        serializer = AttachmentUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        file_key = generate_file_key("attachments", data["file_name"])
        upload_url = generate_presigned_upload_url(file_key, data["content_type"])

        attachment = Attachment.objects.create(
            task=task,
            uploaded_by=request.user,
            file_name=data["file_name"],
            file_key=file_key,
            file_size=data["file_size"],
            content_type=data["content_type"],
        )

        logger.info(
            "attachment_upload_initiated",
            task_id=str(task_pk),
            attachment_id=str(attachment.id),
            use_s3=settings.USE_S3,
        )

        return Response(
            AttachmentUploadResponseSerializer({
                "upload_url": upload_url,
                "file_key": file_key,
                "attachment_id": attachment.id,
            }).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="upload-local",
        parser_classes=[MultiPartParser],
    )
    def upload_local(self, request, task_pk=None):
        """
        Dev-only endpoint: accepts a multipart file and saves it locally.
        In production USE_S3=True, clients PUT directly to S3 presigned URL.
        """
        task = self._get_task()
        file_obj = request.FILES.get("file")
        attachment_id = request.data.get("attachment_id")

        if not file_obj:
            return Response(
                {"detail": "No file provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if attachment_id:
            # Update existing attachment record created by request_upload
            try:
                attachment = Attachment.objects.get(pk=attachment_id, task=task)
                content = file_obj.read()
                save_file_locally(attachment.file_key, content)
            except Attachment.DoesNotExist:
                return Response(
                    {"detail": "Attachment not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            # Create attachment record and save file in one step
            file_key = generate_file_key("attachments", file_obj.name)
            content = file_obj.read()
            save_file_locally(file_key, content)
            attachment = Attachment.objects.create(
                task=task,
                uploaded_by=request.user,
                file_name=file_obj.name,
                file_key=file_key,
                file_size=len(content),
                content_type=file_obj.content_type or "application/octet-stream",
            )

        return Response(
            AttachmentSerializer(attachment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_destroy(self, instance):
        delete_file(instance.file_key)
        instance.delete()
        logger.info(
            "attachment_deleted",
            attachment_id=str(instance.id),
            deleted_by=str(self.request.user.id),
        )


# ─────────────────────────────────────────────────────────────
# Export Jobs
# ─────────────────────────────────────────────────────────────

class ExportJobViewSet(
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    POST /reports/             — create export job (triggers Celery task)
    GET  /reports/{id}/        — poll status
    GET  /reports/{id}/download/ — get presigned download URL
    """
    serializer_class = ExportJobSerializer
    permission_classes = [IsOrgMember]

    def get_queryset(self):
        return ExportJob.objects.filter(
            organization=self.request.org,
            requested_by=self.request.user,
        )

    def create(self, request, *args, **kwargs):
        serializer = ExportJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        project = get_object_or_404(
            Project,
            pk=serializer.validated_data["project_id"],
            organization=request.org,
            is_deleted=False,
        )

        job = ExportJob.objects.create(
            organization=request.org,
            project=project,
            requested_by=request.user,
            status=ExportJob.Status.PENDING,
        )

        # Queue async PDF generation
        generate_project_report.delay(str(job.id))

        logger.info(
            "export_job_created",
            job_id=str(job.id),
            project_id=str(project.id),
            user_id=str(request.user.id),
        )

        return Response(
            ExportJobSerializer(job, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Return the presigned download URL for a completed export."""
        job = self.get_object()
        if job.status != ExportJob.Status.COMPLETED:
            return Response(
                {"detail": _("Report is not ready yet. Status: ") + job.status},
                status=status.HTTP_400_BAD_REQUEST,
            )
        url = generate_presigned_download_url(job.file_key)
        return Response({"download_url": url})
