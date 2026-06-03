"""
Serializers for the notifications app.
"""
from django.conf import settings
from rest_framework import serializers

from apps.tasks.models import Attachment
from .models import ExportJob, Notification
from .storage import generate_presigned_download_url, generate_presigned_upload_url, generate_file_key


class ActorSerializer(serializers.Serializer):
    """Minimal actor/user representation for notifications."""
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()


class NotificationSerializer(serializers.ModelSerializer):
    actor = ActorSerializer(read_only=True)
    target_type = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id", "verb", "description", "actor",
            "target_type", "target_id",
            "is_read", "created_at",
        ]
        read_only_fields = fields

    def get_target_type(self, obj):
        if obj.target_ct:
            return obj.target_ct.model  # e.g. "task", "project"
        return None


class AttachmentSerializer(serializers.ModelSerializer):
    """Read serializer — includes a time-limited download URL."""
    download_url = serializers.SerializerMethodField()
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id", "file_name", "file_size", "content_type",
            "uploaded_by_name", "download_url", "created_at",
        ]
        read_only_fields = fields

    def get_download_url(self, obj):
        return generate_presigned_download_url(obj.file_key)

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return obj.uploaded_by.full_name or obj.uploaded_by.email
        return None


class AttachmentUploadRequestSerializer(serializers.Serializer):
    """
    Input for requesting a presigned upload URL.
    The client sends file metadata; we return a URL to PUT the file to.
    """
    file_name = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=100)
    file_size = serializers.IntegerField(min_value=1, max_value=50 * 1024 * 1024)  # 50 MB max


class AttachmentUploadResponseSerializer(serializers.Serializer):
    """Response after requesting an upload URL."""
    upload_url = serializers.CharField(allow_null=True)  # null in dev (use local upload)
    file_key = serializers.CharField()
    attachment_id = serializers.UUIDField()


class ExportJobSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = [
            "id", "status", "project_name", "error",
            "download_url", "created_at", "completed_at",
        ]
        read_only_fields = fields

    def get_download_url(self, obj):
        if obj.status == ExportJob.Status.COMPLETED and obj.file_key:
            return generate_presigned_download_url(obj.file_key)
        return None

    def get_project_name(self, obj):
        return obj.project.name if obj.project else None


class ExportJobCreateSerializer(serializers.Serializer):
    """Input for creating an export job."""
    project_id = serializers.UUIDField()
