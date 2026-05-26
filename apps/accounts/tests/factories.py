"""
factory_boy factories for accounts and organizations.

Centralised in conftest.py so all tests share them without re-importing.
"""
import factory
import factory.fuzzy
from django.contrib.auth import get_user_model
from factory.django import DjangoModelFactory

User = get_user_model()


class UserFactory(DjangoModelFactory):
    """Creates a regular active user."""

    class Meta:
        model = User
        skip_postgeneration_save = True  # factory_boy ≥ 4.x

    email = factory.LazyAttribute(lambda o: f"{o.first_name.lower()}.{o.last_name.lower()}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_active = True
    is_verified = True
    password = factory.PostGenerationMethodCall("set_password", "TestPass123!")

    class Params:
        admin = factory.Trait(is_staff=True, is_superuser=True)
        unverified = factory.Trait(is_verified=False)


class OrganizationFactory(DjangoModelFactory):
    """Creates an organization (without memberships)."""

    class Meta:
        model = "organizations.Organization"
        skip_postgeneration_save = True

    name = factory.Faker("company")
    slug = factory.LazyAttribute(
        lambda o: o.name.lower().replace(" ", "-").replace(",", "")[:50]
    )
    owner = factory.SubFactory(UserFactory)
    description = factory.Faker("bs")
    plan = "free"
    is_deleted = False


class MembershipFactory(DjangoModelFactory):
    """Creates a membership binding a user to an org with a role."""

    class Meta:
        model = "organizations.Membership"

    user = factory.SubFactory(UserFactory)
    organization = factory.SubFactory(OrganizationFactory)
    role = "member"
    invited_by = factory.SelfAttribute("organization.owner")
