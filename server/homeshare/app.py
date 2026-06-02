import logging
from datetime import timedelta

import click
from flask import Flask, Response, current_app
from flask_migrate import Migrate
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
from systemd.journal import JournalHandler

from homeshare.auth import auth_bp, init_oauth
from homeshare.config import Config
from homeshare.models import Share, db
from homeshare.storage import cleanup_orphans

csrf = CSRFProtect()


def _setup_logging(level: int = logging.WARNING) -> None:
    handler = JournalHandler(SYSLOG_IDENTIFIER="homeshare")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[{name}] {message}", style="{")
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def create_app(config: Config | None = None) -> Flask:
    log_level = (
        logging.getLevelName(config.log_level)
        if config is not None
        else logging.WARNING
    )
    _setup_logging(log_level)

    app = Flask(__name__)

    if config is not None:
        app.config.update(config.to_flask_config())

    app.config.update(
        {
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": True,
            "SESSION_COOKIE_NAME": "__Host-session",
            "SESSION_PERMANENT": True,
            "PERMANENT_SESSION_LIFETIME": timedelta(hours=24),
            "SESSION_TYPE": "sqlalchemy",
            "SESSION_SQLALCHEMY": db,
        }
    )
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Strict")

    db.init_app(app)
    Migrate(app, db)
    Session(app)
    csrf.init_app(app)

    @app.after_request
    def set_security_headers(response: Response) -> Response:
        # Instruct browsers to only connect over HTTPS for the next year.
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
        # Explicitly allowlist only the resource types used,
        # deny everything else by default.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self'; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'; "
            "upgrade-insecure-requests"
        )
        # Prevent browsers from MIME-sniffing responses away from the declared
        # content type, which can allow content injection attacks.
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Legacy framing protection for older browsers that predate CSP.
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent browsers and proxies from caching any responses.
        # This is important for API tokens that should be shown only once.
        response.headers["Cache-Control"] = "no-store"
        # Allow the Referer header for same-origin navigations so that
        # Flask-WTF's CSRF referer check can validate form submissions,
        # while still preventing share UUIDs and other page URLs from
        # leaking to third-party sites.
        response.headers["Referrer-Policy"] = "same-origin"
        # Deny access to unused sensitive browser APIs,
        # limiting the impact of any XSS vulnerability.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        return response

    @app.cli.command("cleanup")
    def cleanup_command() -> None:
        known = set(db.session.execute(db.select(Share.stored_path)).scalars())
        count = cleanup_orphans(current_app.config["UPLOAD_DIR"], known)
        if count:
            app.logger.info("event=cleanup_orphans deleted=%d", count)
        click.echo(f"Deleted {count} orphan file(s)")

    app.register_blueprint(auth_bp)
    init_oauth(app)

    from homeshare.api import create_api_blueprint
    from homeshare.web import create_web_blueprint

    api_bp = create_api_blueprint(app)
    csrf.exempt(api_bp)
    app.register_blueprint(api_bp)
    create_web_blueprint(app)

    return app
