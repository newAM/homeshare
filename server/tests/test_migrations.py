"""
Tests for database migrations.

These tests exercise the Alembic migration scripts directly using a real
on-disk SQLite database.  They are intentionally separate from the unit tests
in conftest.py, which use an in-memory database and bypass migrations entirely
for speed.

Each test follows the same pattern:

1. Apply all migrations forward to ``head`` (``upgrade``).
2. Assert that the expected schema is present.
3. Roll back one step (``downgrade -1``).
4. Assert that the schema was correctly undone.
5. Re-apply the migration (``upgrade head``).
6. Assert the schema is correct again.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from flask_migrate import downgrade, upgrade
from flask import Flask

from homeshare.config import Config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def migration_config(tmp_path: Path) -> Config:
    """A Config that points at a real on-disk SQLite database.

    Migration tests cannot use ``sqlite:///:memory:`` because Alembic opens
    multiple connections internally and each in-memory database is independent,
    so one connection's schema changes are invisible to another.
    """
    db_path = tmp_path / "migration_test.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    return Config(
        secret_key="test-secret-key",
        upload_dir=str(upload_dir),
        db_url=f"sqlite:///{db_path}",
        oidc_client_id="test-client-id",
        oidc_client_secret="test-client-secret",
        oidc_discovery_url="https://example.com/.well-known/openid-configuration",
        public_url="https://homeshare.example.com",
        roles_path=["roles"],
    )


@pytest.fixture
def migration_app(migration_config: Config) -> Flask:
    """A minimal Flask app backed by a real on-disk SQLite database."""
    from flask_migrate import Migrate
    from homeshare.models import db

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config.update(migration_config.to_flask_config())
    db.init_app(flask_app)
    Migrate(flask_app, db)
    return flask_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_names(app: Flask) -> set[str]:
    """Return the set of table names present in the database."""
    from homeshare.models import db

    with app.app_context():
        inspector = sa.inspect(db.engine)
        return set(inspector.get_table_names())


def _column_names(app: Flask, table: str) -> set[str]:
    """Return the set of column names for *table*."""
    from homeshare.models import db

    with app.app_context():
        inspector = sa.inspect(db.engine)
        return {col["name"] for col in inspector.get_columns(table)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_initial_migration_upgrade_and_downgrade(migration_app: Flask) -> None:
    """The initial migration creates all application tables and can be rolled back."""
    migrations_dir = "migrations"

    # --- forward: all three application tables must exist -------------------
    with migration_app.app_context():
        upgrade(directory=migrations_dir)

    tables_after_upgrade = _table_names(migration_app)
    assert "api_token" in tables_after_upgrade
    assert "share" in tables_after_upgrade
    assert "share_link" in tables_after_upgrade

    # Spot-check a few columns to verify column-level correctness.
    assert "hashed_token" in _column_names(migration_app, "api_token")
    assert "stored_path" in _column_names(migration_app, "share")
    assert "download_count" in _column_names(migration_app, "share_link")

    # --- rollback: the initial migration has no predecessor, so rolling back
    #     should remove all application tables --------------------------------
    with migration_app.app_context():
        downgrade(directory=migrations_dir, revision="-1")

    tables_after_downgrade = _table_names(migration_app)
    assert "api_token" not in tables_after_downgrade
    assert "share" not in tables_after_downgrade
    assert "share_link" not in tables_after_downgrade

    # --- re-apply: idempotency check ----------------------------------------
    with migration_app.app_context():
        upgrade(directory=migrations_dir)

    tables_after_reapply = _table_names(migration_app)
    assert "api_token" in tables_after_reapply
    assert "share" in tables_after_reapply
    assert "share_link" in tables_after_reapply
