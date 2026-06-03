"""
Storage abstraction — S3 with presigned URLs, or local filesystem fallback.

In dev (USE_S3 = False):
  - Files are saved to MEDIA_ROOT/attachments/ and MEDIA_ROOT/reports/
  - "Presigned" upload URL → local POST endpoint (handled by view)
  - Download URL → MEDIA_URL-based path served by Django's static server

In prod (USE_S3 = True):
  - Files are stored in S3 under the configured bucket
  - Presigned PUT URL for direct browser-to-S3 upload
  - Presigned GET URL for time-limited downloads
"""
import os
import uuid

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)


def _s3_client():
    """Lazily create a boto3 S3 client."""
    import boto3
    return boto3.client(
        "s3",
        region_name=settings.AWS_S3_REGION_NAME,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def generate_file_key(prefix, original_name):
    """
    Generate a unique S3 object key (or local path segment).
    Example: attachments/abc123/original_name.pdf
    """
    unique = uuid.uuid4().hex[:12]
    # Sanitise the filename — keep only the basename
    safe_name = os.path.basename(original_name)
    return f"{prefix}/{unique}/{safe_name}"


def generate_presigned_upload_url(file_key, content_type):
    """
    Returns a presigned URL that the browser can PUT the file to directly.

    In dev mode (no S3), returns None — the view handles local upload instead.
    """
    if not settings.USE_S3:
        # Local fallback: the view handles the upload via a multipart POST
        return None

    client = _s3_client()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key": file_key,
            "ContentType": content_type,
        },
        ExpiresIn=settings.AWS_PRESIGNED_EXPIRY,
    )
    logger.debug("presigned_upload_url_generated", key=file_key)
    return url


def generate_presigned_download_url(file_key):
    """
    Returns a presigned GET URL for downloading a file.

    In dev mode, returns a MEDIA_URL-based path that Django's
    static file server can serve.
    """
    if not settings.USE_S3:
        # Local: file lives at MEDIA_ROOT/<file_key>
        return f"{settings.MEDIA_URL}{file_key}"

    client = _s3_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
            "Key": file_key,
        },
        ExpiresIn=settings.AWS_PRESIGNED_EXPIRY,
    )
    logger.debug("presigned_download_url_generated", key=file_key)
    return url


def save_file_locally(file_key, content):
    """
    Save file content to MEDIA_ROOT/<file_key>.
    Creates intermediate directories as needed.
    Used in dev mode for both uploads and report generation.
    """
    full_path = os.path.join(settings.MEDIA_ROOT, file_key)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(full_path, mode) as f:
        f.write(content)
    logger.debug("file_saved_locally", path=full_path)
    return full_path


def delete_file(file_key):
    """Delete a file from S3 or local filesystem."""
    if settings.USE_S3:
        client = _s3_client()
        client.delete_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=file_key,
        )
        logger.info("s3_file_deleted", key=file_key)
    else:
        full_path = os.path.join(settings.MEDIA_ROOT, file_key)
        if os.path.exists(full_path):
            os.remove(full_path)
            logger.info("local_file_deleted", path=full_path)
