import io
import json
import uuid
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from flask.testing import FlaskClient

from conftest import get_csrf_token


def _upload_api(
    client: FlaskClient,
    api_token: str,
    content: bytes = b"data",
    filename: str = "f.txt",
) -> str:
    data: dict = {"file": (io.BytesIO(content), filename)}
    response = client.post(
        "/api/shares",
        data=data,
        content_type="multipart/form-data",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_token}",
        },
    )
    assert response.status_code == 201
    return json.loads(response.data)["share_id"]


# --- HTML tests (web.py) ---


def test_robots_txt_returns_disallow_all(client: FlaskClient) -> None:
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert b"text/plain" in response.content_type.encode()
    assert response.data == b"User-agent: *\nDisallow: /\n"


def test_index_unauthenticated_redirects_to_login(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 302
    assert "login" in response.headers["Location"]


def test_index_authenticated_shows_upload_form(authed_client: FlaskClient) -> None:
    response = authed_client.get("/")
    assert response.status_code == 200
    assert b"Upload" in response.data
    assert b"Sign out" in response.data
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
    assert response.headers["Content-Security-Policy"] == (
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
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["Permissions-Policy"] == (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )


def test_index_lists_shares(authed_client: FlaskClient, api_token: str) -> None:
    _upload_api(authed_client, api_token, filename="listed.txt")
    response = authed_client.get("/")
    assert response.status_code == 200
    assert b"listed.txt" in response.data


def test_upload_without_csrf_token_returns_400(authed_client: FlaskClient) -> None:
    response = authed_client.post(
        "/upload",
        data={"file": (io.BytesIO(b"data"), "f.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_upload_with_invalid_csrf_token_returns_400(
    authed_client: FlaskClient,
) -> None:
    response = authed_client.post(
        "/upload",
        data={"csrf_token": "invalid", "file": (io.BytesIO(b"data"), "f.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_upload_html_redirects_to_share_detail(
    authed_client: FlaskClient,
) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/upload",
        data={"csrf_token": csrf, "file": (io.BytesIO(b"hello"), "hello.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert "/shares/" in response.headers["Location"]


def test_upload_no_file_returns_400(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/upload",
        data={"csrf_token": csrf},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_upload_empty_filename_returns_400(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/upload",
        data={"csrf_token": csrf, "file": (io.BytesIO(b"data"), "")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_upload_invalid_expires_in_returns_400(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/upload",
        data={
            "csrf_token": csrf,
            "file": (io.BytesIO(b"data"), "f.txt"),
            "expires_in": "not-a-date",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


# --- share detail ---


def test_share_detail_shows_links(authed_client: FlaskClient, api_token: str) -> None:
    share_id = _upload_api(authed_client, api_token, filename="detail.txt")
    response = authed_client.get(f"/shares/{share_id}")
    assert response.status_code == 200
    assert b"detail.txt" in response.data
    assert b"Create link" in response.data


def test_share_detail_unauthenticated_returns_404(
    client: FlaskClient, api_token: str, authed_client: FlaskClient
) -> None:
    share_id = _upload_api(authed_client, api_token)
    response = client.get(f"/shares/{share_id}")
    assert response.status_code == 404


# --- create link via web ---


def test_create_link_via_form(authed_client: FlaskClient, api_token: str) -> None:
    share_id = _upload_api(authed_client, api_token, filename="linked.txt")
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/shares/{share_id}/links",
        data={"csrf_token": csrf, "label": "for Bob", "expires_in": "7 days"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert f"/shares/{share_id}" in response.headers["Location"]

    response = authed_client.get(f"/shares/{share_id}")
    assert b"for Bob" in response.data


def test_create_link_invalid_duration_returns_400(
    authed_client: FlaskClient, api_token: str
) -> None:
    share_id = _upload_api(authed_client, api_token)
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/shares/{share_id}/links",
        data={"csrf_token": csrf, "expires_in": "bad"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


# --- delete link via web ---


def test_delete_link_via_form(authed_client: FlaskClient, api_token: str) -> None:
    share_id = _upload_api(authed_client, api_token, content=b"kept")
    response = authed_client.get(f"/shares/{share_id}")
    assert response.status_code == 200

    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/shares/{share_id}/links",
        data={"csrf_token": csrf, "label": "to delete"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    from homeshare.models import ShareLink, db

    with authed_client.application.app_context():
        link = db.session.execute(
            db.select(ShareLink).where(ShareLink.label == "to delete")
        ).scalar_one()
        link_id = link.link_id

    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/links/{link_id}",
        data={"csrf_token": csrf, "_method": "DELETE"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302

    response = authed_client.get(f"/links/{link_id}/download")
    assert response.status_code == 404


# --- delete share via web ---


def test_delete_share_via_form_redirects_to_index(
    authed_client: FlaskClient, api_token: str
) -> None:
    share_id = _upload_api(authed_client, api_token)
    csrf = get_csrf_token(authed_client)

    response = authed_client.post(
        f"/shares/{share_id}",
        data={"csrf_token": csrf, "_method": "DELETE"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_delete_share_via_form_removes_share(
    authed_client: FlaskClient, api_token: str
) -> None:
    share_id = _upload_api(authed_client, api_token)

    from homeshare.models import Share, db

    with authed_client.application.app_context():
        share = db.session.get(Share, uuid.UUID(share_id))
        assert share is not None
        stored_path = share.stored_path

    csrf = get_csrf_token(authed_client)
    authed_client.post(
        f"/shares/{share_id}",
        data={"csrf_token": csrf, "_method": "DELETE"},
    )
    assert not Path(stored_path).exists(), f"file still on disk: {stored_path}"


def test_delete_without_csrf_token_returns_400(
    authed_client: FlaskClient, api_token: str
) -> None:
    share_id = _upload_api(authed_client, api_token)

    response = authed_client.post(
        f"/shares/{share_id}",
        data={"_method": "DELETE"},
    )
    assert response.status_code == 400


def test_delete_unauthenticated_returns_404(
    authed_client: FlaskClient, client: FlaskClient, api_token: str
) -> None:
    share_id = _upload_api(authed_client, api_token)
    csrf = get_csrf_token(client)

    response = client.post(
        f"/shares/{share_id}",
        data={"csrf_token": csrf, "_method": "DELETE"},
    )
    assert response.status_code == 404


def test_delete_other_users_share_returns_404(
    authed_client: FlaskClient, app: Flask, api_token: str
) -> None:
    share_id = _upload_api(authed_client, api_token)

    other_client = app.test_client()
    with other_client.session_transaction() as sess:
        sess["user"] = {
            "sub": "other-user-sub",
            "email": "other@example.com",
            "name": "Other",
            "roles": ["homeshare_users"],
        }

    csrf = get_csrf_token(other_client)
    response = other_client.post(
        f"/shares/{share_id}",
        data={"csrf_token": csrf, "_method": "DELETE"},
    )
    assert response.status_code == 404


def test_delete_nonexistent_share_returns_404(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/shares/{uuid.uuid4()}",
        data={"csrf_token": csrf, "_method": "DELETE"},
    )
    assert response.status_code == 404


# --- download via web ---


def test_download_via_web_link(client: FlaskClient, api_token: str) -> None:
    data: dict = {"file": (io.BytesIO(b"hello world"), "dl.txt")}
    response = client.post(
        "/api/shares",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    link_id = json.loads(response.data)["link_id"]

    response = client.get(f"/links/{link_id}/download")
    assert response.status_code == 200
    assert response.data == b"hello world"


def test_logout_get_returns_405(authed_client: FlaskClient) -> None:
    response = authed_client.get("/logout")
    assert response.status_code == 405


def test_logout_post_without_csrf_returns_400(
    authed_client: FlaskClient,
) -> None:
    response = authed_client.post("/logout")
    assert response.status_code == 400


def test_logout_post_with_csrf_clears_session(
    authed_client: FlaskClient,
) -> None:
    csrf = get_csrf_token(authed_client)
    with patch("homeshare.auth.oauth.oidc.load_server_metadata", return_value={}):
        response = authed_client.post("/logout", data={"csrf_token": csrf})
    assert response.status_code == 302
    with authed_client.session_transaction() as sess:
        assert sess.get("user") is None


# --- role tests ---


def test_index_user_without_role_returns_403(
    unroled_client: FlaskClient,
) -> None:
    response = unroled_client.get("/")
    assert response.status_code == 403
    assert b"homeshare_users" in response.data
    assert b"Permission denied" in response.data


def test_account_user_without_role_returns_403(
    unroled_client: FlaskClient,
) -> None:
    response = unroled_client.get("/account")
    assert response.status_code == 403
    assert b"homeshare_users" in response.data


def test_index_admin_role_allowed(admin_client: FlaskClient) -> None:
    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"Upload" in response.data


def test_account_admin_role_allowed(admin_client: FlaskClient) -> None:
    response = admin_client.get("/account")
    assert response.status_code == 200


def test_upload_user_without_role_returns_403(
    unroled_client: FlaskClient,
) -> None:
    csrf = get_csrf_token(unroled_client)
    response = unroled_client.post(
        "/upload",
        data={"csrf_token": csrf, "file": (io.BytesIO(b"data"), "f.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 403
