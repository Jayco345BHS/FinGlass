from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("id",)
    list_display = ("id", "username", "auth_provider", "is_active", "is_staff")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identity", {"fields": ("auth_provider", "external_subject")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "is_active", "is_staff"),
            },
        ),
    )
    search_fields = ("username", "external_subject")
