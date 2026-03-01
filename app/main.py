import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, url_for

from .context import get_current_user
from .db import close_db, init_db
from .routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("SECRET_KEY")
        or "finglass-dev-secret-change-me"
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

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
