from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    PUBLIC_PATHS = {
        "/login",
        "/api/auth/login",
        "/api/auth/register",
        "/__django__/health/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if self._is_public(path):
            return self.get_response(request)

        if request.user.is_authenticated:
            return self.get_response(request)

        if path.startswith("/api/"):
            return JsonResponse({"error": "Authentication required"}, status=401)

        return redirect("/login")

    def _is_public(self, path):
        return (
            path in self.PUBLIC_PATHS
            or path.startswith("/static/")
            or path.startswith("/admin/")
        )


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        if not path.startswith("/static/"):
            get_token(request)

        response = self.get_response(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        return response
