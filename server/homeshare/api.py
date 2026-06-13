import functools
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    jsonify,
    make_response,
    request,
    send_file,
)
from flask.typing import ResponseReturnValue
from sqlalchemy import update
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from homeshare.auth import UserSession
from homeshare.models import ApiToken, Share, ShareLink, db
from homeshare.storage import delete_file, get_file, save_file
from homeshare.tokens import hash_token
from homeshare_common.duration import MAX_EXPIRES_IN


def get_owned_share(owner: str, share_id: uuid.UUID) -> Share | None:
    """Look up a share belonging to the given owner, returning None if not found or not owned."""
    share = db.session.get(Share, share_id)
    if share is None or share.owner != owner:
        return None
    return share


def get_link(link_id: uuid.UUID) -> ShareLink | None:
    """Look up a share link by ID, returning None if not found."""
    return db.session.execute(
        db.select(ShareLink).where(ShareLink.link_id == link_id)
    ).scalar_one_or_none()


def list_shares(owner: str) -> list[Share]:
    """Return all shares owned by the given user."""
    return list(
        db.session.execute(db.select(Share).where(Share.owner == owner)).scalars().all()
    )


def list_tokens(owner: str) -> list[ApiToken]:
    """Return all API tokens owned by the given user, newest first."""
    return list(
        db.session.execute(
            db.select(ApiToken)
            .where(ApiToken.owner == owner)
            .order_by(ApiToken.created_at.desc())
        )
        .scalars()
        .all()
    )


def list_links(share_id: uuid.UUID) -> list[ShareLink]:
    """Return all links for a share."""
    return list(
        db.session.execute(
            db.select(ShareLink)
            .where(ShareLink.share_id == share_id)
            .order_by(ShareLink.created_at.desc())
        )
        .scalars()
        .all()
    )


def create_share(file: FileStorage, owner: str, upload_dir: str) -> Share:
    """Save an uploaded file to disk and create a Share record."""
    stored_path = save_file(file, upload_dir)
    safe_filename = secure_filename(file.filename or "upload") or "upload"
    share = Share(
        filename=safe_filename,
        stored_path=stored_path,
        owner=owner,
    )
    db.session.add(share)
    db.session.commit()
    return share


def create_link(
    share_id: uuid.UUID,
    label: str | None = None,
    expires_in: int | None = None,
) -> ShareLink:
    """Create a new download link for a share."""
    link = ShareLink(
        share_id=share_id,
        label=label,
        expires_in=expires_in,
    )
    db.session.add(link)
    db.session.commit()
    return link


def _bearer_user() -> UserSession | None:
    """Return the authenticated user from a Bearer token, or None."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    token_hash = hash_token(token)
    record = db.session.execute(
        db.select(ApiToken).where(ApiToken.hashed_token == token_hash)
    ).scalar_one_or_none()
    if record is None or record.is_expired:
        # Accepted risk: distinguishing expired from invalid tokens in logs leaks
        # information to anyone with log access. This is intentional, the distinction
        # improves UX by allowing operators to diagnose token expiry issues quickly.
        reason = "expired" if record and record.is_expired else "invalid"
        current_app.logger.warning("event=auth_failed reason=%s", reason)
        return None
    record.last_used_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"sub": record.owner}


def require_auth(
    f: Callable[..., ResponseReturnValue],
) -> Callable[..., ResponseReturnValue]:
    """Decorator that injects the authenticated user as the first argument.

    Calls abort(401) if the request carries no valid Bearer token, which is
    handled by the api blueprint's 401 error handler and returns JSON.
    """

    @functools.wraps(f)
    def wrapper(*args: object, **kwargs: object) -> ResponseReturnValue:
        user = _bearer_user()
        if user is None:
            abort(401)
        return f(user, *args, **kwargs)

    return wrapper


def _parse_expires_in_seconds(raw: str | None) -> int | None:
    """Parse an expires_in form field value.

    Returns None if raw is empty/None, the parsed positive integer otherwise,
    or raises abort(400) on invalid input.
    """
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        abort(400, description="expires_in must be a positive integer (seconds)")
    if value <= 0:
        abort(400, description="expires_in must be a positive integer (seconds)")
    if value > MAX_EXPIRES_IN:
        abort(400, description=f"expires_in must not exceed {MAX_EXPIRES_IN} seconds")
    return value


def download_response(link_id: uuid.UUID, upload_dir: str) -> Response:
    """Resolve a download link and return a Flask response.

    Returns a file response on success, or a JSON error response for
    a missing/expired link (404/410).
    """
    link = get_link(link_id)
    if link is None:
        return make_response(jsonify({"error": "Not found"}), 404)
    if link.is_expired:
        return make_response(jsonify({"error": "This link has expired"}), 410)

    share = link.share

    try:
        file_path = get_file(share.stored_path, upload_dir)
    except (FileNotFoundError, ValueError):
        return make_response(jsonify({"error": "Not found"}), 404)

    db.session.execute(
        update(ShareLink)
        .where(ShareLink.link_id == link_id)
        .values(download_count=ShareLink.download_count + 1)
    )
    db.session.commit()

    current_app.logger.info(
        "event=download share_id=%s link_id=%s", share.share_id, link_id
    )
    return send_file(
        file_path,
        download_name=share.filename,
        as_attachment=True,
        mimetype="application/octet-stream",
    )


def upload_response(user_sub: str, upload_dir: str, expires_in: int | None) -> Response:
    """Upload a file and return a JSON response.

    Returns JSON 201 with share_id and link_id on success, or JSON 400 if no
    file was provided.
    """
    file = request.files.get("file")
    if file is None or file.filename == "":
        return make_response(jsonify({"error": "No file provided"}), 400)

    share = create_share(file=file, owner=user_sub, upload_dir=upload_dir)
    link = create_link(share_id=share.share_id, expires_in=expires_in)

    current_app.logger.info(
        "event=upload user_sub=%r share_id=%s filename=%s expires_in=%s",
        user_sub,
        share.share_id,
        share.filename,
        expires_in,
    )
    return make_response(
        jsonify({"share_id": str(share.share_id), "link_id": str(link.link_id)}), 201
    )


def create_link_response(
    user_sub: str, share_id: uuid.UUID, label: str | None, expires_in: int | None
) -> Response:
    """Create a link for a share and return a JSON response.

    Returns the new link as JSON 201, a JSON 400 if the label exceeds 64
    characters, or a JSON 404 if the share is not found or not owned by
    user_sub.
    """
    if label is not None and len(label) > 64:
        return make_response(
            jsonify({"error": "Link label must be 64 characters or fewer"}), 400
        )

    share = get_owned_share(user_sub, share_id)
    if share is None:
        return make_response(jsonify({"error": "Not found"}), 404)

    link = create_link(share_id=share_id, label=label, expires_in=expires_in)
    current_app.logger.info(
        "event=create_link user_sub=%s share_id=%s link_id=%s label=%r",
        user_sub,
        share_id,
        link.link_id,
        label,
    )
    return make_response(jsonify(link.to_dict()), 201)


def delete_share_response(
    user_sub: str, share_id: uuid.UUID, upload_dir: str
) -> Response:
    """Delete a share and return a JSON response.

    Returns JSON 200 on success, or JSON 404 if not found or not owned by user_sub.
    """
    share = get_owned_share(user_sub, share_id)
    if share is None:
        return make_response(jsonify({"error": "Not found"}), 404)

    current_app.logger.info(
        "event=delete_share user_sub=%r share_id=%s",
        user_sub,
        share_id,
    )
    stored_path = share.stored_path
    db.session.delete(share)
    db.session.commit()
    delete_file(stored_path, upload_dir)
    return make_response(jsonify({"status": "deleted"}), 200)


def delete_link_response(user_sub: str, link_id: uuid.UUID) -> Response:
    """Delete a link and return a JSON response.

    Returns JSON 200 on success, or JSON 404 if not found or not owned by user_sub.
    """
    link = get_link(link_id)
    if link is None or link.share.owner != user_sub:
        return make_response(jsonify({"error": "Not found"}), 404)

    current_app.logger.info(
        "event=delete_link user_sub=%r link_id=%s",
        user_sub,
        link_id,
    )
    db.session.delete(link)
    db.session.commit()
    return make_response(
        jsonify({"status": "deleted", "share_id": str(link.share_id)}), 200
    )


def create_api_blueprint(app: Flask) -> Blueprint:
    api_bp = Blueprint("api", __name__, url_prefix="/api")

    @api_bp.route("/health")
    def health() -> Response:
        return jsonify({"status": "ok"})

    @api_bp.route("/me")
    @require_auth
    def me(user: UserSession) -> Response:
        return jsonify({"sub": user["sub"]})

    @api_bp.route("/shares", methods=["GET"])
    @require_auth
    def list_shares_route(user: UserSession) -> Response:
        return jsonify([s.to_dict() for s in list_shares(user["sub"])])

    @api_bp.route("/shares", methods=["POST"])
    @require_auth
    def upload(user: UserSession) -> Response:
        expires_in = _parse_expires_in_seconds(request.form.get("expires_in"))
        return upload_response(user["sub"], app.config["UPLOAD_DIR"], expires_in)

    @api_bp.route("/shares/<uuid:share_id>/links", methods=["GET"])
    @require_auth
    def list_links_route(user: UserSession, share_id: uuid.UUID) -> ResponseReturnValue:
        share = get_owned_share(user["sub"], share_id)
        if share is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify([link.to_dict() for link in list_links(share_id)])

    @api_bp.route("/shares/<uuid:share_id>/links", methods=["POST"])
    @require_auth
    def create_link_route(user: UserSession, share_id: uuid.UUID) -> Response:
        label = request.form.get("label") or None
        expires_in = _parse_expires_in_seconds(request.form.get("expires_in"))
        return create_link_response(user["sub"], share_id, label, expires_in)

    @api_bp.route("/links/<uuid:link_id>/download")
    def download(link_id: uuid.UUID) -> Response:
        return download_response(link_id, app.config["UPLOAD_DIR"])

    @api_bp.route("/shares/<uuid:share_id>", methods=["DELETE"])
    @require_auth
    def delete_share(user: UserSession, share_id: uuid.UUID) -> Response:
        return delete_share_response(user["sub"], share_id, app.config["UPLOAD_DIR"])

    @api_bp.route("/links/<uuid:link_id>", methods=["DELETE"])
    @require_auth
    def delete_link(user: UserSession, link_id: uuid.UUID) -> Response:
        return delete_link_response(user["sub"], link_id)

    @api_bp.errorhandler(400)
    def bad_request(e: Exception) -> tuple[Response, int]:
        description = getattr(e, "description", "bad request")
        return jsonify({"error": description}), 400

    @api_bp.errorhandler(401)
    def unauthorized(_e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "unauthorized"}), 401

    @api_bp.errorhandler(404)
    def not_found(_e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "not found"}), 404

    @api_bp.errorhandler(405)
    def method_not_allowed(_e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "method not allowed"}), 405

    @api_bp.errorhandler(413)
    def request_too_large(_e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "request too large"}), 413

    @api_bp.errorhandler(500)
    def server_error(_e: Exception) -> tuple[Response, int]:
        return jsonify({"error": "internal server error"}), 500

    return api_bp
