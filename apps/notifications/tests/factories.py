"""
Factories for notifications app tests.
"""
import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import UserFactory, OrganizationFactory
from apps.tasks.models import Attachment
from apps.notifications.models import ExportJob, Notification


class NotificationFactory(DjangoModelFactory):
    class Meta:
        model = Notification

    recipient = factory.SubFactory(UserFactory)
    actor = factory.SubFactory(UserFactory)
    verb = "task_assigned"
    description = factory.Faker("sentence")
    is_read = False


class AttachmentFactory(DjangoModelFactory):
    class Meta:
        model = Attachment
        skip_postgeneration_save = True

    task = None  # Must be provided by caller
    uploaded_by = factory.SubFactory(UserFactory)
    file_name = factory.Faker("file_name")
    file_key = factory.LazyAttribute(lambda o: f"attachments/test/{o.file_name}")
    file_size = 1024
    content_type = "application/pdf"


class ExportJobFactory(DjangoModelFactory):
    class Meta:
        model = ExportJob

    organization = factory.SubFactory(OrganizationFactory)
    project = None
    requested_by = factory.SubFactory(UserFactory)
    status = ExportJob.Status.PENDING
