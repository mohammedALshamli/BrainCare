from django.test import TestCase

from apps.accounts.forms import UserCreationForm
from apps.accounts.models import User


class UserModelTests(TestCase):
    def test_create_user_normalises_email(self):
        user = User.objects.create_user(
            email="  Patient@Example.COM ", password="Str0ng-Passw0rd!"
        )
        self.assertEqual(user.email, "patient@example.com")
        self.assertTrue(user.check_password("Str0ng-Passw0rd!"))

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="Str0ng-Passw0rd!")

    def test_user_can_hold_both_roles(self):
        user = User.objects.create_user(
            email="dual@example.com",
            password="Str0ng-Passw0rd!",
            is_patient=True,
            is_caregiver=True,
        )
        self.assertEqual(user.roles, ["patient", "caregiver"])
        self.assertTrue(user.has_role("patient"))
        self.assertTrue(user.has_role("caregiver"))

    def test_roles_are_empty_by_default(self):
        user = User.objects.create_user(
            email="plain@example.com", password="Str0ng-Passw0rd!"
        )
        self.assertEqual(user.roles, [])
        self.assertFalse(user.has_role("patient"))

    def test_create_superuser_sets_staff_and_superuser(self):
        user = User.objects.create_superuser(
            email="admin@example.com", password="Str0ng-Passw0rd!"
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertEqual(user.roles, [])

    def test_string_representation_is_email(self):
        user = User.objects.create_user(
            email="name@example.com", password="Str0ng-Passw0rd!"
        )
        self.assertEqual(str(user), "name@example.com")

    def test_full_name(self):
        user = User.objects.create_user(
            email="name@example.com",
            password="Str0ng-Passw0rd!",
            first_name="Ada",
            last_name="Lovelace",
        )
        self.assertEqual(user.get_full_name(), "Ada Lovelace")
        self.assertEqual(user.get_short_name(), "Ada")


class AdminUserCreationFormTests(TestCase):
    def test_admin_form_hashes_the_password(self):
        form = UserCreationForm(
            data={
                "email": "admin-created@example.com",
                "first_name": "Admin",
                "last_name": "Created",
                "is_patient": True,
                "is_caregiver": False,
                "password1": "Str0ng-Passw0rd!",
                "password2": "Str0ng-Passw0rd!",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertNotEqual(user.password, "Str0ng-Passw0rd!")
        self.assertTrue(user.check_password("Str0ng-Passw0rd!"))

    def test_admin_form_rejects_mismatched_passwords(self):
        form = UserCreationForm(
            data={
                "email": "admin-created@example.com",
                "password1": "Str0ng-Passw0rd!",
                "password2": "Different-Passw0rd!",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)
