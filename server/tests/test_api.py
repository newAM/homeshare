import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask
from flask.testing import FlaskClient

from homeshare.models import ApiToken, Share, ShareLink, db
from homeshare.tokens import generate_token, hash_token


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload_api(
    client: FlaskClient,
    token: str,
    content: bytes = b"data",
    filename: str = "f.txt",
    extra: dict | None = None,
) -> tuple[str, str]:
    """Upload via the API and return (share_id, link_id)."""
    data: dict = {"file": (io.BytesIO(content), filename)}
    if extra:
        data.update(extra)
    response = client.post(
        "/api/shares",
        data=data,
        content_type="multipart/form-data",
        headers=_auth_header(token),
    )
    assert response.status_code == 201
    body = json.loads(response.data)
    return body["share_id"], body["link_id"]


def _create_link_api(
    client: FlaskClient,
    token: str,
    share_id: str,
    label: str | None = None,
    expires_in: str | None = None,
) -> str:
    """Create a link via the API and return the link_id."""
    data: dict = {}
    if label:
        data["label"] = label
    if expires_in:
        data["expires_in"] = expires_in
    response = client.post(
        f"/api/shares/{share_id}/links",
        data=data,
        headers=_auth_header(token),
    )
    assert response.status_code == 201
    return json.loads(response.data)["link_id"]


# --- health ---


def test_health_ok(client: FlaskClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "ok"


# --- me ---


def test_me_returns_sub(client: FlaskClient, api_token: str) -> None:
    response = client.get("/api/me", headers=_auth_header(api_token))
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["sub"] == "test-user-sub"


def test_me_unauthenticated_returns_401(client: FlaskClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401


def test_me_expired_token_returns_401(client: FlaskClient, app: Flask) -> None:
    raw = generate_token()
    with app.app_context():
        token = ApiToken(
            owner="testuser",
            name="expired",
            hashed_token=hash_token(raw),
            expires_in=1,
        )
        token.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.session.add(token)
        db.session.commit()
    response = client.get("/api/me", headers=_auth_header(raw))
    assert response.status_code == 401


def test_api_request_updates_last_used_at(
    client: FlaskClient, app: Flask, api_token: str
) -> None:
    token_hash = hash_token(api_token)

    with app.app_context():
        record = db.session.execute(
            db.select(ApiToken).where(ApiToken.hashed_token == token_hash)
        ).scalar_one()
        assert record.last_used_at is None

    response = client.get("/api/me", headers=_auth_header(api_token))
    assert response.status_code == 200

    with app.app_context():
        db.session.expire_all()
        record = db.session.execute(
            db.select(ApiToken).where(ApiToken.hashed_token == token_hash)
        ).scalar_one()
        assert record.last_used_at is not None


# --- list shares ---


def test_list_shares_returns_own_shares(client: FlaskClient, api_token: str) -> None:
    _upload_api(client, api_token, filename="a.txt")
    _upload_api(client, api_token, filename="b.txt")
    response = client.get("/api/shares", headers=_auth_header(api_token))
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) == 2
    filenames = {s["filename"] for s in data}
    assert filenames == {"a.txt", "b.txt"}


def test_list_shares_includes_links(client: FlaskClient, api_token: str) -> None:
    share_id, link_id = _upload_api(client, api_token)
    response = client.get("/api/shares", headers=_auth_header(api_token))
    data = json.loads(response.data)
    share = next(s for s in data if s["share_id"] == share_id)
    assert any(lnk["link_id"] == link_id for lnk in share["links"])


def test_list_shares_does_not_include_other_users(
    client: FlaskClient, app: Flask, api_token: str
) -> None:
    _upload_api(client, api_token, filename="mine.txt")

    other_raw = generate_token()
    with app.app_context():
        db.session.add(
            ApiToken(
                name="other",
                hashed_token=hash_token(other_raw),
                owner="other-user-sub",
            )
        )
        db.session.commit()
    _upload_api(client, other_raw, filename="theirs.txt")

    response = client.get("/api/shares", headers=_auth_header(api_token))
    data = json.loads(response.data)
    assert all(s["filename"] != "theirs.txt" for s in data)


def test_list_shares_unauthenticated_returns_401(client: FlaskClient) -> None:
    response = client.get("/api/shares")
    assert response.status_code == 401


# --- upload ---


def test_upload_returns_share_and_link_ids(client: FlaskClient, api_token: str) -> None:
    share_id, link_id = _upload_api(client, api_token)
    uuid.UUID(share_id)
    uuid.UUID(link_id)


def test_upload_unauthenticated_returns_401(client: FlaskClient) -> None:
    response = client.post(
        "/api/shares",
        data={"file": (io.BytesIO(b"hello world"), "hello.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401


def test_upload_no_file_returns_400(client: FlaskClient, api_token: str) -> None:
    response = client.post(
        "/api/shares",
        data={},
        content_type="multipart/form-data",
        headers=_auth_header(api_token),
    )
    assert response.status_code == 400


def test_upload_empty_filename_returns_400(client: FlaskClient, api_token: str) -> None:
    response = client.post(
        "/api/shares",
        data={"file": (io.BytesIO(b"data"), "")},
        content_type="multipart/form-data",
        headers=_auth_header(api_token),
    )
    assert response.status_code == 400


def test_upload_sets_owner(client: FlaskClient, api_token: str, app: Flask) -> None:
    share_id, _ = _upload_api(client, api_token)

    with app.app_context():
        share = db.session.get(Share, uuid.UUID(share_id))
        assert share is not None
        assert share.owner == "test-user-sub"


def test_upload_with_expires_in(
    client: FlaskClient, api_token: str, app: Flask
) -> None:
    _share_id, link_id = _upload_api(client, api_token, extra={"expires_in": "3600"})

    with app.app_context():
        link = db.session.execute(
            db.select(ShareLink).where(ShareLink.link_id == uuid.UUID(link_id))
        ).scalar_one()
        assert link.expires_in == 3600


def test_upload_invalid_expires_in_returns_400(
    client: FlaskClient, api_token: str
) -> None:
    response = client.post(
        "/api/shares",
        data={
            "file": (io.BytesIO(b"data"), "f.txt"),
            "expires_in": "not-a-number",
        },
        content_type="multipart/form-data",
        headers=_auth_header(api_token),
    )
    assert response.status_code == 400


# --- links ---


def test_create_link(client: FlaskClient, api_token: str) -> None:
    share_id, _ = _upload_api(client, api_token)
    link_id = _create_link_api(
        client, api_token, share_id, label="for Alice", expires_in="7200"
    )
    uuid.UUID(link_id)


def test_create_link_for_other_users_share_returns_404(
    client: FlaskClient, app: Flask, api_token: str
) -> None:
    share_id, _ = _upload_api(client, api_token)

    other_raw = generate_token()
    with app.app_context():
        db.session.add(
            ApiToken(
                name="other",
                hashed_token=hash_token(other_raw),
                owner="other-user-sub",
            )
        )
        db.session.commit()

    response = client.post(
        f"/api/shares/{share_id}/links",
        data={"label": "stolen"},
        headers=_auth_header(other_raw),
    )
    assert response.status_code == 404


def test_list_links(client: FlaskClient, api_token: str) -> None:
    share_id, first_link_id = _upload_api(client, api_token)
    second_link_id = _create_link_api(client, api_token, share_id, label="second link")

    response = client.get(
        f"/api/shares/{share_id}/links", headers=_auth_header(api_token)
    )
    assert response.status_code == 200
    links = json.loads(response.data)
    link_ids = {lnk["link_id"] for lnk in links}
    assert first_link_id in link_ids
    assert second_link_id in link_ids


# --- download ---


def test_download_returns_file_contents(client: FlaskClient, api_token: str) -> None:
    _, link_id = _upload_api(client, api_token, content=b"hello world")
    response = client.get(f"/api/links/{link_id}/download")
    assert response.status_code == 200
    assert response.data == b"hello world"
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Disposition"].startswith("attachment")


def test_download_unknown_id_returns_404(client: FlaskClient) -> None:
    response = client.get(f"/api/links/{uuid.uuid4()}/download")
    assert response.status_code == 404


def test_download_does_not_require_auth(client: FlaskClient, api_token: str) -> None:
    _, link_id = _upload_api(client, api_token, content=b"public content")
    response = client.get(f"/api/links/{link_id}/download")
    assert response.status_code == 200
    assert response.data == b"public content"


def test_download_increments_download_count(
    client: FlaskClient, api_token: str, app: Flask
) -> None:
    _, link_id = _upload_api(client, api_token, content=b"data")
    client.get(f"/api/links/{link_id}/download")
    client.get(f"/api/links/{link_id}/download")

    with app.app_context():
        link = db.session.execute(
            db.select(ShareLink).where(ShareLink.link_id == uuid.UUID(link_id))
        ).scalar_one()
        assert link.download_count == 2


def test_download_expired_link_returns_410(client: FlaskClient, app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="expired.txt",
            stored_path="/tmp/expired.txt",
            owner="test-user-sub",
        )
        db.session.add(share)
        db.session.commit()

        link = ShareLink(
            share_id=share.share_id,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_in=3600,
        )
        db.session.add(link)
        db.session.commit()
        link_id = str(link.link_id)

    response = client.get(f"/api/links/{link_id}/download")
    assert response.status_code == 410


def test_download_non_expired_link_succeeds(
    client: FlaskClient, api_token: str
) -> None:
    _, link_id = _upload_api(
        client, api_token, content=b"fresh", extra={"expires_in": "3600"}
    )
    response = client.get(f"/api/links/{link_id}/download")
    assert response.status_code == 200
    assert response.data == b"fresh"


# --- delete share ---


def test_delete_own_share(client: FlaskClient, api_token: str) -> None:
    share_id, _ = _upload_api(client, api_token)
    response = client.delete(f"/api/shares/{share_id}", headers=_auth_header(api_token))
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "deleted"
    response = client.get(
        f"/api/shares/{share_id}/links", headers=_auth_header(api_token)
    )
    assert response.status_code == 404


def test_delete_share_unauthenticated_returns_401(
    client: FlaskClient, api_token: str
) -> None:
    share_id, _ = _upload_api(client, api_token)
    response = client.delete(f"/api/shares/{share_id}")
    assert response.status_code == 401


def test_delete_other_users_share_returns_404(
    client: FlaskClient, app: Flask, api_token: str
) -> None:
    share_id, _ = _upload_api(client, api_token)

    other_raw = generate_token()
    with app.app_context():
        db.session.add(
            ApiToken(
                name="other",
                hashed_token=hash_token(other_raw),
                owner="other-user-sub",
            )
        )
        db.session.commit()

    response = client.delete(f"/api/shares/{share_id}", headers=_auth_header(other_raw))
    assert response.status_code == 404


def test_delete_nonexistent_share_returns_404(
    client: FlaskClient, api_token: str
) -> None:
    response = client.delete(
        f"/api/shares/{uuid.uuid4()}", headers=_auth_header(api_token)
    )
    assert response.status_code == 404


def test_delete_share_removes_file_from_disk(
    client: FlaskClient, api_token: str, app: Flask
) -> None:
    share_id, _ = _upload_api(client, api_token, content=b"to be deleted")

    with app.app_context():
        share = db.session.get(Share, uuid.UUID(share_id))
        assert share is not None
        stored_path = share.stored_path

    response = client.delete(f"/api/shares/{share_id}", headers=_auth_header(api_token))
    assert response.status_code == 200

    assert not Path(stored_path).exists(), f"file still on disk: {stored_path}"


# --- delete link ---


def test_delete_own_link(client: FlaskClient, api_token: str) -> None:
    _, link_id = _upload_api(client, api_token)
    response = client.delete(f"/api/links/{link_id}", headers=_auth_header(api_token))
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "deleted"
    response = client.get(f"/api/links/{link_id}/download")
    assert response.status_code == 404


def test_delete_link_does_not_delete_file(client: FlaskClient, api_token: str) -> None:
    share_id, link_id = _upload_api(client, api_token, content=b"kept")
    second_link_id = _create_link_api(client, api_token, share_id)

    client.delete(f"/api/links/{link_id}", headers=_auth_header(api_token))

    response = client.get(f"/api/links/{second_link_id}/download")
    assert response.status_code == 200
    assert response.data == b"kept"


def test_delete_link_unauthenticated_returns_401(
    client: FlaskClient, api_token: str
) -> None:
    _, link_id = _upload_api(client, api_token)
    response = client.delete(f"/api/links/{link_id}")
    assert response.status_code == 401


def test_delete_other_users_link_returns_404(
    client: FlaskClient, app: Flask, api_token: str
) -> None:
    _, link_id = _upload_api(client, api_token)

    other_raw = generate_token()
    with app.app_context():
        db.session.add(
            ApiToken(
                name="other",
                hashed_token=hash_token(other_raw),
                owner="other-user-sub",
            )
        )
        db.session.commit()

    response = client.delete(f"/api/links/{link_id}", headers=_auth_header(other_raw))
    assert response.status_code == 404
