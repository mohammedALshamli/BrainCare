from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeForm, UserCreationForm
from .models import CaregiverPatientLink, PairingCode, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm

    list_display = (
        "email",
        "first_name",
        "last_name",
        "is_patient",
        "is_caregiver",
        "is_staff",
        "is_active",
    )
    list_filter = (
        "is_patient",
        "is_caregiver",
        "is_staff",
        "is_superuser",
        "is_active",
    )
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    readonly_fields = ("date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Roles", {"fields": ("is_patient", "is_caregiver")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "is_patient",
                    "is_caregiver",
                    "password1",
                    "password2",
                ),
            },
        ),
    )


@admin.register(CaregiverPatientLink)
class CaregiverPatientLinkAdmin(admin.ModelAdmin):
    list_display = (
        "caregiver",
        "patient",
        "is_active",
        "can_view",
        "can_edit_medications",
        "notify_missed_doses",
        "created_at",
    )
    list_filter = (
        "is_active",
        "can_view",
        "can_edit_medications",
        "notify_missed_doses",
    )
    search_fields = (
        "caregiver__email",
        "patient__email",
    )
    readonly_fields = ("created_at", "updated_at", "consent_at", "revoked_at")


@admin.register(PairingCode)
class PairingCodeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient",
        "expires_at",
        "used_at",
        "used_by",
        "invalidated_at",
        "created_at",
    )
    list_filter = ("used_at", "invalidated_at")
    search_fields = ("patient__email", "used_by__email")
    readonly_fields = (
        "id",
        "patient",
        "code_hash",
        "expires_at",
        "used_at",
        "used_by",
        "invalidated_at",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
