"""
Celery tasks for Phase 3.

- send_welcome_email        — on user registration
- send_task_assignment_email — when a task is assigned/reassigned
- send_daily_digest          — Celery Beat, daily at 08:00 UTC
- generate_project_report    — async PDF report via reportlab
"""
import structlog
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_welcome_email(self, user_id):
    """Send a welcome email to a newly registered user."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning("welcome_email_user_not_found", user_id=user_id)
        return

    subject = "Welcome to TaskForge! 🚀"
    message = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"Welcome to TaskForge — your new project management hub.\n\n"
        f"Get started by creating your first organization and project:\n"
        f"{settings.FRONTEND_URL}/\n\n"
        f"Cheers,\nThe TaskForge Team"
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    logger.info("welcome_email_sent", user_id=str(user_id), email=user.email)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_task_assignment_email(self, task_id, assignee_id, assigner_id=None):
    """Send an email when a task is assigned to a user."""
    from django.contrib.auth import get_user_model
    from apps.tasks.models import Task

    User = get_user_model()
    try:
        task = Task.objects.select_related("project").get(pk=task_id)
        assignee = User.objects.get(pk=assignee_id)
    except (Task.DoesNotExist, User.DoesNotExist):
        logger.warning(
            "assignment_email_entity_not_found",
            task_id=task_id,
            assignee_id=assignee_id,
        )
        return

    assigner_name = "Someone"
    if assigner_id:
        try:
            assigner = User.objects.get(pk=assigner_id)
            assigner_name = assigner.full_name or assigner.email
        except User.DoesNotExist:
            pass

    ref = f"TASK-{task.reference}" if task.reference else str(task.id)[:8]
    subject = f"[TaskForge] You've been assigned: {ref} — {task.title}"
    message = (
        f"Hi {assignee.first_name or 'there'},\n\n"
        f"{assigner_name} assigned you a task in {task.project.name}:\n\n"
        f"  {ref}: {task.title}\n"
        f"  Priority: {task.priority}\n"
        f"  Due: {task.due_date or 'No due date'}\n\n"
        f"View it here: {settings.FRONTEND_URL}/\n\n"
        f"— TaskForge"
    )

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[assignee.email],
        fail_silently=False,
    )
    logger.info(
        "assignment_email_sent",
        task_id=str(task_id),
        assignee_email=assignee.email,
    )


@shared_task(bind=True)
def send_daily_digest(self):
    """
    Celery Beat task: send a digest email to users with unread notifications.
    Groups notifications by recipient and sends one email per user.
    """
    from django.contrib.auth import get_user_model
    from apps.notifications.models import Notification

    User = get_user_model()

    # Find users with unread notifications from the last 24 hours
    since = timezone.now() - timezone.timedelta(hours=24)
    recipients = (
        Notification.objects
        .filter(is_read=False, created_at__gte=since)
        .values_list("recipient_id", flat=True)
        .distinct()
    )

    sent_count = 0
    for user_id in recipients:
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            continue

        notifications = (
            Notification.objects
            .filter(recipient=user, is_read=False, created_at__gte=since)
            .order_by("-created_at")[:20]
        )

        if not notifications:
            continue

        lines = [f"  • {n.description}" for n in notifications]
        subject = f"[TaskForge] You have {len(lines)} unread notification{'s' if len(lines) != 1 else ''}"
        message = (
            f"Hi {user.first_name or 'there'},\n\n"
            f"Here's your daily digest:\n\n"
            + "\n".join(lines)
            + f"\n\nView all: {settings.FRONTEND_URL}/\n\n"
            f"— TaskForge"
        )

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
        sent_count += 1

    logger.info("daily_digest_sent", recipient_count=sent_count)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def generate_project_report(self, export_job_id):
    """
    Generate a PDF report for a project and update the ExportJob status.

    Uses reportlab — pure Python, no system dependencies.
    """
    from apps.notifications.models import ExportJob
    from apps.tasks.models import Task, TaskStatus
    from apps.notifications.storage import generate_file_key, save_file_locally

    try:
        job = ExportJob.objects.select_related("project", "organization").get(pk=export_job_id)
    except ExportJob.DoesNotExist:
        logger.error("export_job_not_found", job_id=export_job_id)
        return

    # Mark as processing
    job.status = ExportJob.Status.PROCESSING
    job.save(update_fields=["status"])

    try:
        project = job.project
        org = job.organization

        # Fetch data
        statuses = TaskStatus.objects.filter(project=project).order_by("order")
        tasks = (
            Task.objects
            .filter(project=project, is_deleted=False)
            .select_related("status", "assignee")
            .order_by("status__order", "order")
        )

        # Build PDF
        pdf_bytes = _build_pdf(project, org, statuses, tasks)

        # Save to storage
        file_key = generate_file_key("reports", f"{project.name}_report.pdf")

        if settings.USE_S3:
            import boto3
            s3 = boto3.client(
                "s3",
                region_name=settings.AWS_S3_REGION_NAME,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            s3.put_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=file_key,
                Body=pdf_bytes,
                ContentType="application/pdf",
            )
        else:
            save_file_locally(file_key, pdf_bytes)

        job.status = ExportJob.Status.COMPLETED
        job.file_key = file_key
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "file_key", "completed_at"])
        logger.info("report_generated", job_id=str(export_job_id), file_key=file_key)

    except Exception as exc:
        job.status = ExportJob.Status.FAILED
        job.error = str(exc)
        job.save(update_fields=["status", "error"])
        logger.error("report_generation_failed", job_id=str(export_job_id), error=str(exc))
        raise self.retry(exc=exc)


def _build_pdf(project, org, statuses, tasks):
    """Build a PDF report using reportlab and return bytes."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.grey,
        spaceAfter=20,
    )
    heading_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=14,
        spaceBefore=16,
        spaceAfter=8,
    )

    elements = []

    # Header
    elements.append(Paragraph(f"{project.name} — Project Report", title_style))
    elements.append(Paragraph(
        f"Organization: {org.name} | Generated: {timezone.now().strftime('%Y-%m-%d %H:%M UTC')}",
        subtitle_style,
    ))

    # Summary stats
    total = tasks.count()
    by_priority = {}
    by_status = {}
    for t in tasks:
        by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
        status_name = t.status.name if t.status else "No Status"
        by_status[status_name] = by_status.get(status_name, 0) + 1

    elements.append(Paragraph("Summary", heading_style))
    summary_data = [
        ["Total Tasks", str(total)],
    ]
    for p, c in sorted(by_priority.items()):
        summary_data.append([f"Priority: {p.title()}", str(c)])
    for s, c in sorted(by_status.items()):
        summary_data.append([f"Status: {s}", str(c)])

    summary_table = Table(summary_data, colWidths=[3 * inch, 1.5 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6366f1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    # Task table
    elements.append(Paragraph("All Tasks", heading_style))
    table_data = [["Ref", "Title", "Assignee", "Priority", "Status", "Due"]]
    for t in tasks:
        ref = f"TASK-{t.reference}" if t.reference else "—"
        assignee = t.assignee.full_name if t.assignee else "Unassigned"
        status_name = t.status.name if t.status else "—"
        due = str(t.due_date) if t.due_date else "—"
        # Truncate long titles
        title_text = t.title[:40] + "…" if len(t.title) > 40 else t.title
        table_data.append([ref, title_text, assignee, t.priority.title(), status_name, due])

    if len(table_data) > 1:
        task_table = Table(
            table_data,
            colWidths=[0.7 * inch, 2.2 * inch, 1.2 * inch, 0.8 * inch, 1 * inch, 0.8 * inch],
        )
        task_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6366f1")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(task_table)
    else:
        elements.append(Paragraph("No tasks found in this project.", styles["Normal"]))

    doc.build(elements)
    return buffer.getvalue()
