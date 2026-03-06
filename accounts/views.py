import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import AdminActionLog, User


@require_GET
def first_launch_check_view(request):
    """Check if the app needs first-launch setup (no users exist)"""
    has_users = User.objects.exists()
    return JsonResponse({"has_users": has_users})


@require_POST
def first_launch_setup_view(request):
    """Create the first superadmin user"""
    # Only allow if no users exist
    if User.objects.exists():
        return JsonResponse({"error": "Users already exist"}, status=409)

    payload = _read_json(request)
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not username or not password:
        return JsonResponse({"error": "username and password are required"}, status=400)

    if len(password) < 8:
        return JsonResponse({"error": "password must be at least 8 characters"}, status=400)

    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({"error": "Username already exists"}, status=409)

    # Create superuser
    user = User.objects.create_superuser(username=username, password=password)
    login(request, user)
    return JsonResponse({"id": user.id, "username": user.username, "is_superuser": user.is_superuser})


@require_POST
def register_view(request):
    payload = _read_json(request)
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not username or not password:
        return JsonResponse({"error": "username and password are required"}, status=400)

    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({"error": "Username already exists"}, status=409)

    user = User.objects.create_user(username=username, password=password)
    login(request, user)
    return JsonResponse({"id": user.id, "username": user.username})


@require_POST
def login_view(request):
    payload = _read_json(request)
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not username or not password:
        return JsonResponse({"error": "username and password are required"}, status=400)

    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        return JsonResponse({"error": "Invalid username or password"}, status=401)

    login(request, user)
    return JsonResponse({"id": user.id, "username": user.username})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"ok": True})


@require_GET
def me_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    return JsonResponse(
        {
            "id": request.user.id,
            "username": request.user.username,
            "is_superuser": bool(request.user.is_superuser),
        }
    )


def _ensure_superuser(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    if not request.user.is_superuser:
        return JsonResponse({"error": "Superuser access required"}, status=403)
    return None


def _serialize_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "is_superuser": bool(user.is_superuser),
        "is_staff": bool(user.is_staff),
        "is_active": bool(user.is_active),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def _serialize_audit_log(log):
    actor_username = log.actor.username if log.actor else "Unknown"
    fallback_target = log.target_user.username if log.target_user else ""
    return {
        "id": log.id,
        "action_type": log.action_type,
        "actor_username": actor_username,
        "target_username": log.target_username or fallback_target,
        "details": log.details or {},
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _log_admin_action(*, actor, action_type, target_user=None, target_username="", details=None):
    AdminActionLog.objects.create(
        actor=actor,
        target_user=target_user,
        action_type=str(action_type or "").strip()[:64],
        target_username=str(target_username or (target_user.username if target_user else "")).strip(),
        details=details or {},
    )


@require_GET
def admin_users_list_view(request):
    auth_error = _ensure_superuser(request)
    if auth_error:
        return auth_error

    users = User.objects.order_by("username", "id")
    return JsonResponse({"users": [_serialize_user(user) for user in users]})


@require_POST
def admin_user_set_password_view(request, user_id):
    auth_error = _ensure_superuser(request)
    if auth_error:
        return auth_error

    target_user = User.objects.filter(id=user_id).first()
    if not target_user:
        return JsonResponse({"error": "User not found"}, status=404)

    payload = _read_json(request)
    new_password = str(payload.get("new_password", "")).strip()
    if len(new_password) < 8:
        return JsonResponse({"error": "password must be at least 8 characters"}, status=400)

    target_user.set_password(new_password)
    target_user.save(update_fields=["password", "updated_at"])
    _log_admin_action(
        actor=request.user,
        action_type="set_password",
        target_user=target_user,
    )
    return JsonResponse({"ok": True, "user": _serialize_user(target_user)})


@require_POST
def admin_user_set_superuser_view(request, user_id):
    auth_error = _ensure_superuser(request)
    if auth_error:
        return auth_error

    target_user = User.objects.filter(id=user_id).first()
    if not target_user:
        return JsonResponse({"error": "User not found"}, status=404)

    payload = _read_json(request)
    make_superuser = bool(payload.get("is_superuser", False))

    if target_user.id == request.user.id and not make_superuser:
        return JsonResponse({"error": "You cannot remove your own admin access"}, status=400)

    if not make_superuser and target_user.is_superuser:
        remaining_superusers = User.objects.filter(is_superuser=True).exclude(id=target_user.id).count()
        if remaining_superusers < 1:
            return JsonResponse({"error": "At least one superuser must remain"}, status=400)

    target_user.is_superuser = make_superuser
    target_user.is_staff = make_superuser
    target_user.save(update_fields=["is_superuser", "is_staff", "updated_at"])
    _log_admin_action(
        actor=request.user,
        action_type="grant_admin" if make_superuser else "remove_admin",
        target_user=target_user,
    )
    return JsonResponse({"ok": True, "user": _serialize_user(target_user)})


@require_POST
def admin_user_set_active_view(request, user_id):
    auth_error = _ensure_superuser(request)
    if auth_error:
        return auth_error

    target_user = User.objects.filter(id=user_id).first()
    if not target_user:
        return JsonResponse({"error": "User not found"}, status=404)

    payload = _read_json(request)
    is_active = bool(payload.get("is_active", True))

    if target_user.id == request.user.id and not is_active:
        return JsonResponse({"error": "You cannot deactivate your own account"}, status=400)

    if not is_active and target_user.is_superuser:
        remaining_active_superusers = User.objects.filter(is_superuser=True, is_active=True).exclude(id=target_user.id).count()
        if remaining_active_superusers < 1:
            return JsonResponse({"error": "At least one active superuser must remain"}, status=400)

    target_user.is_active = is_active
    target_user.save(update_fields=["is_active", "updated_at"])
    _log_admin_action(
        actor=request.user,
        action_type="reactivate_user" if is_active else "deactivate_user",
        target_user=target_user,
    )
    return JsonResponse({"ok": True, "user": _serialize_user(target_user)})


@require_http_methods(["DELETE"])
def admin_user_delete_view(request, user_id):
    auth_error = _ensure_superuser(request)
    if auth_error:
        return auth_error

    target_user = User.objects.filter(id=user_id).first()
    if not target_user:
        return JsonResponse({"error": "User not found"}, status=404)

    payload = _read_json(request)
    confirm_username = str(payload.get("confirm_username", "")).strip()
    if confirm_username != target_user.username:
        return JsonResponse({"error": "Type the exact username to confirm deletion"}, status=400)

    if target_user.id == request.user.id:
        return JsonResponse({"error": "You cannot delete your own account"}, status=400)

    if target_user.is_superuser:
        remaining_superusers = User.objects.filter(is_superuser=True).exclude(id=target_user.id).count()
        if remaining_superusers < 1:
            return JsonResponse({"error": "At least one superuser must remain"}, status=400)

    target_username = target_user.username
    _log_admin_action(
        actor=request.user,
        action_type="delete_user",
        target_user=target_user,
        target_username=target_username,
    )
    target_user.delete()
    return JsonResponse({"ok": True})


@require_GET
def admin_audit_logs_view(request):
    auth_error = _ensure_superuser(request)
    if auth_error:
        return auth_error

    try:
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50

    limit = max(1, min(limit, 200))
    logs = AdminActionLog.objects.select_related("actor", "target_user").all()[:limit]
    return JsonResponse({"logs": [_serialize_audit_log(log) for log in logs]})


def _read_json(request):
    try:
        if not request.body:
            return {}
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


@require_POST
def change_password_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)

    payload = _read_json(request)
    current_password = str(payload.get("current_password", "")).strip()
    new_password = str(payload.get("new_password", "")).strip()

    if not current_password or not new_password:
        return JsonResponse({"error": "current_password and new_password are required"}, status=400)

    if len(new_password) < 8:
        return JsonResponse({"error": "password must be at least 8 characters"}, status=400)

    if not request.user.check_password(current_password):
        return JsonResponse({"error": "Current password is incorrect"}, status=401)

    request.user.set_password(new_password)
    request.user.save()
    return JsonResponse({"ok": True})
