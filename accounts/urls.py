from django.urls import path

from .views import (
    admin_audit_logs_view,
    admin_user_delete_view,
    admin_user_set_active_view,
    admin_user_set_password_view,
    admin_user_set_superuser_view,
    admin_users_list_view,
    first_launch_check_view,
    first_launch_setup_view,
    login_view,
    logout_view,
    me_view,
    register_view,
    change_password_view,
)

urlpatterns = [
    path("check-setup", first_launch_check_view, name="check-setup"),
    path("setup-superuser", first_launch_setup_view, name="setup-superuser"),
    path("register", register_view, name="auth-register"),
    path("login", login_view, name="auth-login"),
    path("logout", logout_view, name="auth-logout"),
    path("me", me_view, name="auth-me"),
    path("change-password", change_password_view, name="change-password"),
    path("admin/users", admin_users_list_view, name="admin-users-list"),
    path("admin/users/<int:user_id>/password", admin_user_set_password_view, name="admin-user-set-password"),
    path("admin/users/<int:user_id>/superuser", admin_user_set_superuser_view, name="admin-user-set-superuser"),
    path("admin/users/<int:user_id>/active", admin_user_set_active_view, name="admin-user-set-active"),
    path("admin/users/<int:user_id>", admin_user_delete_view, name="admin-user-delete"),
    path("admin/audit-logs", admin_audit_logs_view, name="admin-audit-logs"),
]
