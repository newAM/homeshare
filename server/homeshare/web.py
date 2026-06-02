import functools
import importlib.metadata
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from authlib.integrations.base_client import OAuthError

from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from homeshare.api import (
    create_link_response,
    delete_link_response,
    delete_share_response,
    download_response,
    get_owned_share,
    list_links,
    list_shares,
    list_tokens,
    upload_response,
)
from homeshare.auth import UserSession, current_user, oauth
from homeshare.models import ApiToken, db
from homeshare.tokens import generate_token, hash_token
from homeshare_common.duration import parse_duration


def _project_urls() -> dict[str, str]:
    entries = (
        importlib.metadata.metadata("homeshare-server").get_all("Project-URL") or []
    )
    return dict(entry.split(", ", 1) for entry in entries)


_REPO_URL = _project_urls()["Repository"]

web_bp = Blueprint("web", __name__)


def _parse_expires_in_duration(raw: str | None) -> int | None:
    """Parse an expires_in duration string from a web form.

    Returns None if raw is falsy, or the parsed duration in seconds.
    Raises ValueError with a user-friendly message on invalid input.
    """
    if not raw:
        return None
    try:
        return parse_duration(raw)
    except ValueError:
        # Do not include the original exception text, it includes unsanitized
        # user input.
        raise ValueError(
            "Invalid duration format. Examples: '7 days', '2h30m', 'never'"
        ) from None


def _html_error_or(resp: Response) -> Response | tuple[str, int]:
    """Remap a JSON error response to an HTML error page.

    If resp has a 4xx/5xx status code, returns an HTML error page using the
    message from the JSON body.  Otherwise returns resp unchanged.
    """
    if resp.status_code >= 400:
        message = resp.get_json().get("error", "An unspecified error occurred")
        return render_template(
            "error.html", code=resp.status_code, message=message
        ), resp.status_code
    return resp


def _has_required_role(user: UserSession) -> bool:
    roles = user.get("roles", [])
    user_role = current_app.config["USER_ROLE"]
    admin_role = current_app.config["ADMIN_ROLE"]
    return user_role in roles or admin_role in roles


def _role_denied_response() -> tuple[str, int]:
    user_role = current_app.config["USER_ROLE"]
    message = (
        f"Permission denied. Contact your system administrator and request "
        f"the {user_role!r} role."
    )
    return render_template("error.html", code=403, message=message), 403


def require_web_auth(
    f: Callable[..., ResponseReturnValue],
) -> Callable[..., ResponseReturnValue]:
    """Decorator that injects the authenticated user as the first argument.

    Returns an HTML 404 error page if no session user is found, or a 403
    permission denied page if the user lacks the required role.
    """

    @functools.wraps(f)
    def wrapper(*args: object, **kwargs: object) -> ResponseReturnValue:
        user = current_user()
        if user is None:
            return render_template("error.html", code=404, message="Not found"), 404
        if not _has_required_role(user):
            return _role_denied_response()
        return f(user, *args, **kwargs)

    return wrapper


def create_web_blueprint(app: Flask) -> None:
    @web_bp.context_processor
    def inject_template_context() -> dict[str, Callable[[datetime], str] | str]:
        def format_created_at(created_at: datetime) -> str:
            return created_at.strftime("%Y-%m-%d %H:%M UTC")

        def to_isoformat(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()

        return {
            "format_created_at": format_created_at,
            "to_isoformat": to_isoformat,
            "repo_url": _REPO_URL,
        }

    @web_bp.route("/")
    def index() -> ResponseReturnValue:
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login"))
        if not _has_required_role(user):
            return _role_denied_response()

        return render_template("index.html", user=user, shares=list_shares(user["sub"]))

    @web_bp.route("/logged-out")
    def logged_out() -> ResponseReturnValue:
        if request.args.get("state"):
            try:
                oauth.oidc.validate_logout_response()
            except OAuthError:
                current_app.logger.warning(
                    "event=logout_validation_failed", exc_info=True
                )
                return render_template(
                    "error.html", code=400, message="Logout validation failed"
                ), 400
        return render_template("logged_out.html")

    @web_bp.route("/account")
    def account() -> ResponseReturnValue:
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login"))
        if not _has_required_role(user):
            return _role_denied_response()

        return render_template(
            "account.html", user=user, tokens=list_tokens(user["sub"])
        )

    @web_bp.route("/account/tokens", methods=["POST"])
    @require_web_auth
    def create_token(user: UserSession) -> ResponseReturnValue:
        name = request.form.get("name", "").strip()
        if len(name) > 64:
            return render_template(
                "error.html",
                code=400,
                message="Token name must be 64 characters or fewer",
            ), 400
        if not name:
            return render_template(
                "error.html", code=400, message="Token name is required"
            ), 400

        try:
            expires_in = _parse_expires_in_duration(
                request.form.get("expires_in", "").strip() or None
            )
        except ValueError as e:
            return render_template("error.html", code=400, message=str(e)), 400

        raw_token = generate_token()
        token = ApiToken(
            name=name,
            hashed_token=hash_token(raw_token),
            owner=user["sub"],
            expires_in=expires_in,
        )
        db.session.add(token)
        db.session.commit()
        current_app.logger.info(
            "event=token_created user_sub=%r token_name=%r",
            user["sub"],
            name,
        )

        return render_template(
            "account.html",
            user=user,
            tokens=list_tokens(user["sub"]),
            new_token=raw_token,
            new_token_name=name,
        ), 201

    @web_bp.route("/account/tokens/<int:token_id>", methods=["POST"])
    @require_web_auth
    def delete_token(user: UserSession, token_id: int) -> ResponseReturnValue:
        if request.form.get("_method") != "DELETE":
            return (
                render_template("error.html", code=405, message="Method not allowed"),
                405,
            )

        token = db.session.get(ApiToken, token_id)
        if token is None or token.owner != user["sub"]:
            return render_template("error.html", code=404, message="Not found"), 404

        db.session.delete(token)
        db.session.commit()
        current_app.logger.info(
            "event=token_deleted user_sub=%r token_id=%s",
            user["sub"],
            token_id,
        )
        return redirect(url_for("web.account"))

    @web_bp.route("/robots.txt")
    def robots_txt() -> ResponseReturnValue:
        content = "User-agent: *\nDisallow: /\n"
        return Response(content, mimetype="text/plain")

    @web_bp.route("/upload", methods=["POST"])
    @require_web_auth
    def upload(user: UserSession) -> ResponseReturnValue:
        try:
            expires_in = _parse_expires_in_duration(request.form.get("expires_in"))
        except ValueError as e:
            return render_template("error.html", code=400, message=str(e)), 400

        resp = upload_response(
            user["sub"], current_app.config["UPLOAD_DIR"], expires_in
        )
        if resp.status_code >= 400:
            return _html_error_or(resp)
        share_id = resp.get_json()["share_id"]
        return redirect(url_for("web.share_detail", share_id=share_id))

    @web_bp.route("/shares/<uuid:share_id>")
    @require_web_auth
    def share_detail(user: UserSession, share_id: uuid.UUID) -> ResponseReturnValue:
        share = get_owned_share(user["sub"], share_id)
        if share is None:
            return render_template("error.html", code=404, message="Not found"), 404

        links = list_links(share_id)
        return render_template("share_detail.html", user=user, share=share, links=links)

    @web_bp.route("/shares/<uuid:share_id>/links", methods=["POST"])
    @require_web_auth
    def create_link_route(
        user: UserSession, share_id: uuid.UUID
    ) -> ResponseReturnValue:
        label = request.form.get("label", "").strip() or None
        try:
            expires_in = _parse_expires_in_duration(request.form.get("expires_in"))
        except ValueError as e:
            return render_template("error.html", code=400, message=str(e)), 400

        resp = create_link_response(user["sub"], share_id, label, expires_in)
        if resp.status_code >= 400:
            return _html_error_or(resp)
        return redirect(url_for("web.share_detail", share_id=share_id))

    @web_bp.route("/links/<uuid:link_id>", methods=["POST"])
    @require_web_auth
    def delete_link(user: UserSession, link_id: uuid.UUID) -> ResponseReturnValue:
        if request.form.get("_method") != "DELETE":
            return (
                render_template("error.html", code=405, message="Method not allowed"),
                405,
            )

        resp = delete_link_response(user["sub"], link_id)
        if resp.status_code >= 400:
            return _html_error_or(resp)
        link_data = resp.get_json()
        return redirect(url_for("web.share_detail", share_id=link_data["share_id"]))

    @web_bp.route("/shares/<uuid:share_id>", methods=["POST"])
    @require_web_auth
    def delete_share(user: UserSession, share_id: uuid.UUID) -> ResponseReturnValue:
        if request.form.get("_method") != "DELETE":
            return (
                render_template("error.html", code=405, message="Method not allowed"),
                405,
            )

        resp = delete_share_response(
            user["sub"], share_id, current_app.config["UPLOAD_DIR"]
        )
        if resp.status_code >= 400:
            return _html_error_or(resp)
        return redirect(url_for("web.index"))

    @web_bp.route("/links/<uuid:link_id>/download")
    def download(link_id: uuid.UUID) -> ResponseReturnValue:
        return _html_error_or(
            download_response(link_id, current_app.config["UPLOAD_DIR"])
        )

    @web_bp.errorhandler(403)
    def forbidden(_e: Exception) -> ResponseReturnValue:
        return render_template("error.html", code=403, message="Forbidden"), 403

    @web_bp.errorhandler(404)
    def not_found(_e: Exception) -> ResponseReturnValue:
        return render_template("error.html", code=404, message="Not found"), 404

    @web_bp.errorhandler(500)
    def server_error(_e: Exception) -> ResponseReturnValue:
        return render_template(
            "error.html", code=500, message="Internal server error"
        ), 500

    app.register_blueprint(web_bp)
