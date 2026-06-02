import json
import logging
from pathlib import Path

import pytest

from homeshare.auth import value_at_path
from homeshare.config import Config, ConfigError, load_config


class TestValueAtPath:
    def test_simple_path(self) -> None:
        data = {"roles": ["admin", "user"]}
        assert value_at_path(data, ["roles"]) == ["admin", "user"]

    def test_nested_path(self) -> None:
        data = {"resource_access": {"client": {"roles": ["homeshare_user"]}}}
        assert value_at_path(data, ["resource_access", "client", "roles"]) == [
            "homeshare_user"
        ]

    def test_missing_key_returns_empty(self) -> None:
        assert value_at_path({"foo": "bar"}, ["baz"]) == []

    def test_missing_nested_key_returns_empty(self) -> None:
        data = {"a": {"b": {"c": ["role1"]}}}
        assert value_at_path(data, ["a", "x", "c"]) == []

    def test_non_dict_intermediate_returns_empty(self) -> None:
        data = {"a": "not a dict"}
        assert value_at_path(data, ["a", "b"]) == []

    def test_non_list_value_returns_empty(self) -> None:
        data = {"roles": 42}
        assert value_at_path(data, ["roles"]) == []

    def test_mixed_list_returns_empty(self) -> None:
        data = {"roles": ["admin", 42]}
        assert value_at_path(data, ["roles"]) == []

    def test_string_value_wrapped_in_list(self) -> None:
        data = {"role": "admin"}
        assert value_at_path(data, ["role"]) == ["admin"]

    def test_empty_path(self) -> None:
        data = {"roles": ["admin"]}
        assert value_at_path(data, []) == []

    def test_empty_list_value(self) -> None:
        data = {"roles": []}
        assert value_at_path(data, ["roles"]) == []


class TestConfigRoles:
    def test_roles_path_required(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        secret_file = tmp_path / "secret"
        secret_file.write_text("a" * 32)
        client_secret_file = tmp_path / "client_secret"
        client_secret_file.write_text("secret")
        config_file.write_text(
            json.dumps(
                {
                    "OIDC_CLIENT_ID": "id",
                    "OIDC_CLIENT_SECRET_FILE": str(client_secret_file),
                    "OIDC_DISCOVERY_URL": "https://example.com/.well-known/openid-configuration",
                    "PUBLIC_URL": "https://homeshare.example.com",
                    "SECRET_KEY_FILE": str(secret_file),
                    "UPLOAD_DIR": str(tmp_path / "uploads"),
                }
            )
        )
        with pytest.raises(ConfigError, match="ROLES_PATH"):
            load_config(config_file)

    def test_roles_path_must_be_list(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        secret_file = tmp_path / "secret"
        secret_file.write_text("a" * 32)
        client_secret_file = tmp_path / "client_secret"
        client_secret_file.write_text("secret")
        config_file.write_text(
            json.dumps(
                {
                    "OIDC_CLIENT_ID": "id",
                    "OIDC_CLIENT_SECRET_FILE": str(client_secret_file),
                    "OIDC_DISCOVERY_URL": "https://example.com/.well-known/openid-configuration",
                    "PUBLIC_URL": "https://homeshare.example.com",
                    "SECRET_KEY_FILE": str(secret_file),
                    "UPLOAD_DIR": str(tmp_path / "uploads"),
                    "ROLES_PATH": "not-a-list",
                }
            )
        )
        with pytest.raises(ConfigError, match="ROLES_PATH must be a non-empty list"):
            load_config(config_file)

    def test_roles_path_must_not_be_empty(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        secret_file = tmp_path / "secret"
        secret_file.write_text("a" * 32)
        client_secret_file = tmp_path / "client_secret"
        client_secret_file.write_text("secret")
        config_file.write_text(
            json.dumps(
                {
                    "OIDC_CLIENT_ID": "id",
                    "OIDC_CLIENT_SECRET_FILE": str(client_secret_file),
                    "OIDC_DISCOVERY_URL": "https://example.com/.well-known/openid-configuration",
                    "PUBLIC_URL": "https://homeshare.example.com",
                    "SECRET_KEY_FILE": str(secret_file),
                    "UPLOAD_DIR": str(tmp_path / "uploads"),
                    "ROLES_PATH": [],
                }
            )
        )
        with pytest.raises(ConfigError, match="ROLES_PATH must be a non-empty list"):
            load_config(config_file)

    def test_valid_roles_path(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        secret_file = tmp_path / "secret"
        secret_file.write_text("a" * 32)
        client_secret_file = tmp_path / "client_secret"
        client_secret_file.write_text("secret")
        config_file.write_text(
            json.dumps(
                {
                    "OIDC_CLIENT_ID": "id",
                    "OIDC_CLIENT_SECRET_FILE": str(client_secret_file),
                    "OIDC_DISCOVERY_URL": "https://example.com/.well-known/openid-configuration",
                    "PUBLIC_URL": "https://homeshare.example.com",
                    "SECRET_KEY_FILE": str(secret_file),
                    "UPLOAD_DIR": str(tmp_path / "uploads"),
                    "ROLES_PATH": ["resource_access", "client", "roles"],
                }
            )
        )
        config = load_config(config_file)
        assert config.roles_path == ["resource_access", "client", "roles"]
        assert config.user_role == "homeshare_users"
        assert config.admin_role == "homeshare_admins"

    def test_custom_role_names(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        secret_file = tmp_path / "secret"
        secret_file.write_text("a" * 32)
        client_secret_file = tmp_path / "client_secret"
        client_secret_file.write_text("secret")
        config_file.write_text(
            json.dumps(
                {
                    "OIDC_CLIENT_ID": "id",
                    "OIDC_CLIENT_SECRET_FILE": str(client_secret_file),
                    "OIDC_DISCOVERY_URL": "https://example.com/.well-known/openid-configuration",
                    "PUBLIC_URL": "https://homeshare.example.com",
                    "SECRET_KEY_FILE": str(secret_file),
                    "UPLOAD_DIR": str(tmp_path / "uploads"),
                    "ROLES_PATH": ["roles"],
                    "USER_ROLE": "my-custom-user",
                    "ADMIN_ROLE": "my-custom-admin",
                }
            )
        )
        config = load_config(config_file)
        assert config.user_role == "my-custom-user"
        assert config.admin_role == "my-custom-admin"

    def test_user_role_in_flask_config(self, tmp_path: Path) -> None:
        config = Config(
            secret_key="test-secret-key",
            upload_dir=str(tmp_path),
            db_url="sqlite:///:memory:",
            oidc_client_id="id",
            oidc_client_secret="secret",
            oidc_discovery_url="https://example.com/.well-known/openid-configuration",
            public_url="https://homeshare.example.com",
            roles_path=["groups"],
            user_role="custom_user",
            admin_role="custom_admin",
        )
        flask_config = config.to_flask_config()
        assert flask_config["ROLES_PATH"] == ["groups"]
        assert flask_config["USER_ROLE"] == "custom_user"
        assert flask_config["ADMIN_ROLE"] == "custom_admin"


def _write_minimal_config(tmp_path: Path, extra: dict | None = None) -> Path:
    """Write a valid minimal config JSON and return the path to it."""
    secret_file = tmp_path / "secret"
    secret_file.write_text("a" * 32)
    client_secret_file = tmp_path / "client_secret"
    client_secret_file.write_text("secret")
    data: dict = {
        "OIDC_CLIENT_ID": "id",
        "OIDC_CLIENT_SECRET_FILE": str(client_secret_file),
        "OIDC_DISCOVERY_URL": "https://example.com/.well-known/openid-configuration",
        "PUBLIC_URL": "https://homeshare.example.com",
        "SECRET_KEY_FILE": str(secret_file),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "ROLES_PATH": ["roles"],
    }
    if extra:
        data.update(extra)
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(data))
    return config_file


class TestLogLevel:
    def test_default_log_level_is_warning(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path))
        assert config.log_level == "WARNING"

    def test_explicit_warning(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "WARNING"}))
        assert config.log_level == "WARNING"

    def test_debug_level(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "DEBUG"}))
        assert config.log_level == "DEBUG"

    def test_info_level(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "INFO"}))
        assert config.log_level == "INFO"

    def test_error_level(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "ERROR"}))
        assert config.log_level == "ERROR"

    def test_critical_level(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "CRITICAL"}))
        assert config.log_level == "CRITICAL"

    def test_lowercase_accepted(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "debug"}))
        assert config.log_level == "DEBUG"

    def test_mixed_case_accepted(self, tmp_path: Path) -> None:
        config = load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "Warning"}))
        assert config.log_level == "WARNING"

    def test_invalid_level_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="LOG_LEVEL"):
            load_config(_write_minimal_config(tmp_path, {"LOG_LEVEL": "VERBOSE"}))

    def test_config_dataclass_default(self, tmp_path: Path) -> None:
        config = Config(
            secret_key="test-secret-key",
            upload_dir=str(tmp_path),
            db_url="sqlite:///:memory:",
            oidc_client_id="id",
            oidc_client_secret="secret",
            oidc_discovery_url="https://example.com/.well-known/openid-configuration",
            public_url="https://homeshare.example.com",
            roles_path=["roles"],
        )
        assert config.log_level == "WARNING"

    def test_setup_logging_uses_configured_level(self) -> None:
        """_setup_logging sets the root logger to the requested level."""
        from homeshare.app import _setup_logging

        _setup_logging(logging.DEBUG)
        assert logging.getLogger().level == logging.DEBUG

    def test_setup_logging_root_always_warning(self) -> None:
        """Root logger is set to WARNING by default."""
        from homeshare.app import _setup_logging

        _setup_logging(logging.WARNING)
        assert logging.getLogger().level == logging.WARNING
