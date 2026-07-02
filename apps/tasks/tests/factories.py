"""
Factory-boy factories for tasks app tests.
"""
import factory
import factory.fuzzy
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import OrganizationFactory, UserFactory


class ProjectFactory(DjangoModelFactory):
    class Meta:
        model = "tasks.Project"

    name = factory.Sequence(lambda n: f"Project {n}")
    description = factory.Faker("sentence")
    organization = factory.SubFactory(OrganizationFactory)
    owner = factory.SubFactory(UserFactory)
    archived = False
    is_deleted = False


class TaskStatusFactory(DjangoModelFactory):
    class Meta:
        model = "tasks.TaskStatus"

    name = factory.Sequence(lambda n: f"Status {n}")
    color = "#6366f1"
    project = factory.SubFactory(ProjectFactory)
    order = factory.Sequence(lambda n: n * 10)


class LabelFactory(DjangoModelFactory):
    class Meta:
        model = "tasks.Label"

    name = factory.Sequence(lambda n: f"Label {n}")
    color = "#f59e0b"
    project = factory.SubFactory(ProjectFactory)


class TaskFactory(DjangoModelFactory):
    class Meta:
        model = "tasks.Task"

    title = factory.Faker("sentence", nb_words=4)
    description = factory.Faker("paragraph")
    project = factory.SubFactory(ProjectFactory)
    status = factory.SubFactory(TaskStatusFactory, project=factory.SelfAttribute("..project"))
    priority = "medium"
    order = factory.Sequence(lambda n: n * 1000)
    is_deleted = False

    @factory.post_generation
    def assignees(self, create, extracted, **kwargs):
        """Usage: TaskFactory(assignees=[user1, user2])"""
        if create and extracted:
            self.assignees.set(extracted)


class SubTaskFactory(DjangoModelFactory):
    class Meta:
        model = "tasks.SubTask"

    title = factory.Faker("sentence", nb_words=3)
    completed = False
    task = factory.SubFactory(TaskFactory)
    order = factory.Sequence(lambda n: n * 10)


class CommentFactory(DjangoModelFactory):
    class Meta:
        model = "tasks.Comment"

    task = factory.SubFactory(TaskFactory)
    author = factory.SubFactory(UserFactory)
    body = factory.Faker("paragraph")
