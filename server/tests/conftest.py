from collections.abc import Generator
import secrets

import pytest
from flask import Flask
from flask.testing import FlaskClient
from itsdangerous import URLSafeTimedSerializer

from homeshare.app import create_app
from homeshare.config import Config
from homeshare.models import ApiToken, db
from homeshare.tokens import generate_token, hash_token


@pytest.fixture(scope="session")
def config(tmp_path_factory: pytest.TempPathFactory) -> Config:
    tmp_path = tmp_path_factory.mktemp("uploads")
    return Config(
        secret_key="test-secret-key",
        upload_dir=str(tmp_path),
        db_url="sqlite:///:memory:",
        oidc_client_id="test-client-id",
        oidc_client_secret="test-client-secret",
        oidc_discovery_url="https://example.com/.well-known/openid-configuration",
        public_url="https://homeshare.example.com",
        roles_path=["roles"],
    )


@pytest.fixture(scope="session")
def app(config: Config) -> Generator[Flask, None, None]:
    flask_app = create_app(config)
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.create_all()
        yield flask_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def authed_client(app: Flask) -> FlaskClient:
    """A test client with a pre-populated session simulating a logged-in user."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {
            "sub": "test-user-sub",
            "email": "test@example.com",
            "name": "Test User",
            "roles": ["homeshare_users"],
        }
    return client


@pytest.fixture
def unroled_client(app: Flask) -> FlaskClient:
    """A test client with a logged-in user who has no valid roles."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {
            "sub": "unroled-user-sub",
            "email": "unroled@example.com",
            "name": "Unroled User",
            "roles": [],
        }
    return client


@pytest.fixture
def admin_client(app: Flask) -> FlaskClient:
    """A test client with a logged-in user who has the admin role."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {
            "sub": "admin-user-sub",
            "email": "admin@example.com",
            "name": "Admin User",
            "roles": ["homeshare_admins"],
        }
    return client


@pytest.fixture
def api_token(app: Flask) -> str:
    """Create an API token for the test user and return the raw token."""
    raw = generate_token()
    with app.app_context():
        token = ApiToken(
            name="test-token",
            hashed_token=hash_token(raw),
            owner="test-user-sub",
        )
        db.session.add(token)
        db.session.commit()
    return raw


def get_csrf_token(client: FlaskClient) -> str:
    """Get a CSRF token for the given test client."""
    with client.session_transaction() as sess:
        if "csrf_token" not in sess:
            sess["csrf_token"] = secrets.token_hex(32)
        csrf_secret = sess["csrf_token"]
    secret_key = client.application.secret_key
    assert secret_key is not None
    s = URLSafeTimedSerializer(secret_key, salt="wtf-csrf-token")
    return s.dumps(csrf_secret)
