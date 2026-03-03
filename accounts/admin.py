import json

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpResponse
from django.utils.timezone import now

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
    actions = ["make_active", "make_inactive", "make_staff", "export_user_data", "delete_user_data", "view_statistics"]

    @admin.action(description="Mark selected users as active")
    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} user(s) marked as active.")

    @admin.action(description="Mark selected users as inactive")
    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} user(s) marked as inactive.")

    @admin.action(description="Mark selected users as staff")
    def make_staff(self, request, queryset):
        updated = queryset.update(is_staff=True)
        self.message_user(request, f"{updated} user(s) marked as staff.")

    @admin.action(description="Export user data as JSON")
    def export_user_data(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Export only works for a single user at a time.", level=admin.messages.ERROR)
            return

        user = queryset.first()
        # Gather all user-related data
        data = {
            'user': {'id': user.id, 'username': user.username},
            'auth_provider': user.auth_provider,
            'is_active': user.is_active,
            'is_staff': user.is_staff,
            'created_at': str(user.created_at),
            'exported_at': str(now())
        }

        response = HttpResponse(json.dumps(data, indent=2), content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="user_{user.id}_data.json"'
        return response

    @admin.action(description="Delete user and all associated data")
    def delete_user_data(self, request, queryset):
        count = queryset.count()
        # This will cascade delete all related records
        queryset.delete()
        self.message_user(request, f"{count} user(s) and all associated data deleted.")

    @admin.action(description="View user statistics")
    def view_statistics(self, request, queryset):
        from django.contrib.admin import messages
        stats = []
        for user in queryset:
            stats.append(f"{user.username}: active={user.is_active}, staff={user.is_staff}")
        message = " | ".join(stats) if stats else "No users selected."
        self.message_user(request, message)
