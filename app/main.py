import os
import secrets
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, session, url_for

from .context import get_current_user
from .db import close_db, init_db
from .routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    configured_secret = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY")
    app.secret_key = configured_secret or secrets.token_urlsafe(64)
    if not configured_secret:
        app.logger.warning(
            "No FLASK_SECRET_KEY/SECRET_KEY provided; generated ephemeral secret key. "
            "Set FLASK_SECRET_KEY in production to keep sessions stable across restarts."
        )

    secure_cookie_default = os.environ.get("FLASK_ENV") == "production"
    secure_cookie_override = os.environ.get("SESSION_COOKIE_SECURE")
    if secure_cookie_override is None:
        session_cookie_secure = secure_cookie_default
    else:
        session_cookie_secure = secure_cookie_override.strip().lower() in {"1", "true", "yes", "on"}

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=session_cookie_secure,
        SESSION_COOKIE_SAMESITE="Strict",
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    )
    app.permanent_session_lifetime = timedelta(days=30)

    init_db()
    app.teardown_appcontext(close_db)

    @app.before_request
    def require_authentication():
        path = request.path or ""
        if path.startswith("/static/"):
            return None
        if path in {"/login", "/api/auth/login", "/api/auth/register"}:
            return None

        if get_current_user():
            return None

        if path.startswith("/api/"):
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("auth.login_page"))

    @app.before_request
    def enforce_csrf_protection():
        path = request.path or ""
        if path.startswith("/static/"):
            return None

        csrf_token = session.get("csrf_token")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf_token

        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None

        header_token = request.headers.get("X-CSRF-Token", "")
        if not header_token or not secrets.compare_digest(str(header_token), str(csrf_token)):
            return jsonify({"error": "CSRF token missing or invalid"}), 403

        return None

    @app.after_request
    def apply_security_headers(response):
        csrf_token = session.get("csrf_token")
        if csrf_token:
            response.set_cookie(
                "csrf_token",
                csrf_token,
                secure=app.config.get("SESSION_COOKIE_SECURE", False),
                httponly=False,
                samesite="Strict",
                max_age=int(app.permanent_session_lifetime.total_seconds()),
            )

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

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
