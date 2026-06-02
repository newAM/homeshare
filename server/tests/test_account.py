from flask import Flask
from flask.testing import FlaskClient

from conftest import get_csrf_token
from homeshare.models import ApiToken, db
from homeshare.tokens import generate_token, hash_token


def test_account_unauthenticated_redirects_to_login(client: FlaskClient) -> None:
    response = client.get("/account")
    assert response.status_code == 302
    assert "login" in response.headers["Location"]


def test_account_shows_empty_tokens(authed_client: FlaskClient) -> None:
    response = authed_client.get("/account")
    assert response.status_code == 200
    assert b"No tokens yet" in response.data


def test_account_shows_user_roles(authed_client: FlaskClient) -> None:
    response = authed_client.get("/account")
    assert response.status_code == 200
    assert b"homeshare_users" in response.data
    assert b"Roles:" in response.data


def test_account_shows_existing_tokens(authed_client: FlaskClient, app: Flask) -> None:
    with app.app_context():
        token = ApiToken(
            name="my-token",
            hashed_token=hash_token(generate_token()),
            owner="test-user-sub",
        )
        db.session.add(token)
        db.session.commit()

    response = authed_client.get("/account")
    assert response.status_code == 200
    assert b"my-token" in response.data


def test_create_token(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/account/tokens",
        data={"csrf_token": csrf, "name": "new-api-token"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    assert b"new-api-token" in response.data
    assert b"hs_" in response.data
    assert b"be shown again" in response.data


def test_create_token_with_expiry(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/account/tokens",
        data={
            "csrf_token": csrf,
            "name": "expiring-token",
            "expires_in": "30 days",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    assert b"expiring-token" in response.data


def test_create_token_no_name_returns_400(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/account/tokens",
        data={"csrf_token": csrf, "name": ""},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_create_token_invalid_duration_returns_400(authed_client: FlaskClient) -> None:
    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        "/account/tokens",
        data={
            "csrf_token": csrf,
            "name": "bad-token",
            "expires_in": "not-a-duration",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_create_token_without_csrf_returns_400(authed_client: FlaskClient) -> None:
    response = authed_client.post(
        "/account/tokens",
        data={"name": "no-csrf"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_delete_token(authed_client: FlaskClient, app: Flask) -> None:
    with app.app_context():
        token = ApiToken(
            name="to-delete",
            hashed_token=hash_token(generate_token()),
            owner="test-user-sub",
        )
        db.session.add(token)
        db.session.commit()
        token_id = token.id

    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/account/tokens/{token_id}",
        data={"csrf_token": csrf, "_method": "DELETE"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account")

    with app.app_context():
        assert db.session.get(ApiToken, token_id) is None


def test_delete_other_users_token_returns_404(
    authed_client: FlaskClient, app: Flask
) -> None:
    with app.app_context():
        token = ApiToken(
            name="other-token",
            hashed_token=hash_token(generate_token()),
            owner="other-user-sub",
        )
        db.session.add(token)
        db.session.commit()
        token_id = token.id

    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/account/tokens/{token_id}",
        data={"csrf_token": csrf, "_method": "DELETE"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 404


def test_delete_token_without_csrf_returns_400(
    authed_client: FlaskClient, app: Flask
) -> None:
    with app.app_context():
        token = ApiToken(
            name="no-csrf-delete",
            hashed_token=hash_token(generate_token()),
            owner="test-user-sub",
        )
        db.session.add(token)
        db.session.commit()
        token_id = token.id

    response = authed_client.post(
        f"/account/tokens/{token_id}",
        data={"_method": "DELETE"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_delete_token_without_method_override_returns_405(
    authed_client: FlaskClient, app: Flask
) -> None:
    with app.app_context():
        token = ApiToken(
            name="bad-method",
            hashed_token=hash_token(generate_token()),
            owner="test-user-sub",
        )
        db.session.add(token)
        db.session.commit()
        token_id = token.id

    csrf = get_csrf_token(authed_client)
    response = authed_client.post(
        f"/account/tokens/{token_id}",
        data={"csrf_token": csrf},
        content_type="multipart/form-data",
    )
    assert response.status_code == 405
