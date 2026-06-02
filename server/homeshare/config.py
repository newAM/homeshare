import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(Exception):
    pass


DEFAULT_MAX_CONTENT_LENGTH = 1024 * 1024 * 1024  # 1 GiB
DEFAULT_LOG_LEVEL = "WARNING"
VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

REQUIRED_KEYS = {
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET_FILE",
    "OIDC_DISCOVERY_URL",
    "PUBLIC_URL",
    "ROLES_PATH",
    "SECRET_KEY_FILE",
    "UPLOAD_DIR",
}


@dataclass
class Config:
    secret_key: str
    upload_dir: str
    db_url: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_discovery_url: str
    public_url: str
    roles_path: list[str]
    user_role: str = "homeshare_users"
    admin_role: str = "homeshare_admins"
    max_content_length: int = DEFAULT_MAX_CONTENT_LENGTH
    session_cookie_samesite: str = "Strict"
    log_level: str = DEFAULT_LOG_LEVEL

    def to_flask_config(self) -> dict:
        return {
            "SECRET_KEY": self.secret_key,
            "UPLOAD_DIR": self.upload_dir,
            "SQLALCHEMY_DATABASE_URI": self.db_url,
            "MAX_CONTENT_LENGTH": self.max_content_length,
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_CLIENT_SECRET": self.oidc_client_secret,
            "OIDC_DISCOVERY_URL": self.oidc_discovery_url,
            "PUBLIC_URL": self.public_url,
            "ROLES_PATH": self.roles_path,
            "USER_ROLE": self.user_role,
            "ADMIN_ROLE": self.admin_role,
            "SESSION_COOKIE_SAMESITE": self.session_cookie_samesite,
        }


def load_config(path: str | Path) -> Config:
    path = Path(path)

    if not path.exists():
        raise ConfigError(f"config file not found: {path}")

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config file is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError("config file must be a JSON object")

    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise ConfigError(
            f"config file is missing required keys: {', '.join(sorted(missing))}"
        )

    secret_key_file = Path(data["SECRET_KEY_FILE"])
    if not secret_key_file.exists():
        raise ConfigError(f"secret key file not found: {secret_key_file}")

    secret_key = secret_key_file.read_text().strip()
    if not secret_key:
        raise ConfigError(f"secret key file is empty: {secret_key_file}")
    if len(secret_key) < 32:
        raise ConfigError("secret key must be at least 32 characters")

    oidc_client_secret_file = Path(data["OIDC_CLIENT_SECRET_FILE"])
    if not oidc_client_secret_file.exists():
        raise ConfigError(
            f"OIDC client secret file not found: {oidc_client_secret_file}"
        )

    oidc_client_secret = oidc_client_secret_file.read_text().strip()
    if not oidc_client_secret:
        raise ConfigError(
            f"OIDC client secret file is empty: {oidc_client_secret_file}"
        )

    max_content_length = data.get("MAX_CONTENT_LENGTH", DEFAULT_MAX_CONTENT_LENGTH)
    if not isinstance(max_content_length, int) or max_content_length <= 0:
        raise ConfigError("MAX_CONTENT_LENGTH must be a positive integer")

    roles_path = data.get("ROLES_PATH")
    if not isinstance(roles_path, list) or len(roles_path) == 0:
        raise ConfigError("ROLES_PATH must be a non-empty list of strings")
    if not all(isinstance(p, str) for p in roles_path):
        raise ConfigError("ROLES_PATH must be a non-empty list of strings")

    user_role = data.get("USER_ROLE", "homeshare_users")
    if not isinstance(user_role, str) or not user_role:
        raise ConfigError("USER_ROLE must be a non-empty string")

    admin_role = data.get("ADMIN_ROLE", "homeshare_admins")
    if not isinstance(admin_role, str) or not admin_role:
        raise ConfigError("ADMIN_ROLE must be a non-empty string")

    session_cookie_samesite = data.get("SESSION_COOKIE_SAMESITE", "Strict")
    if session_cookie_samesite not in {"Strict", "Lax"}:
        raise ConfigError("SESSION_COOKIE_SAMESITE must be 'Strict' or 'Lax'")

    log_level = data.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError(
            f"LOG_LEVEL must be one of: {', '.join(sorted(VALID_LOG_LEVELS))}"
        )

    public_url = data["PUBLIC_URL"]
    _validate_https_url(public_url, "PUBLIC_URL")

    oidc_discovery_url = data["OIDC_DISCOVERY_URL"]
    _validate_https_url(oidc_discovery_url, "OIDC_DISCOVERY_URL")

    return Config(
        secret_key=secret_key,
        upload_dir=data["UPLOAD_DIR"],
        db_url=data.get("DATABASE_URL", "sqlite:////var/lib/homeshare/homeshare.db"),
        oidc_client_id=data["OIDC_CLIENT_ID"],
        oidc_client_secret=oidc_client_secret,
        oidc_discovery_url=oidc_discovery_url,
        max_content_length=max_content_length,
        public_url=public_url,
        roles_path=roles_path,
        user_role=user_role,
        admin_role=admin_role,
        session_cookie_samesite=session_cookie_samesite,
        log_level=log_level,
    )


def _validate_https_url(url: str, name: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"{name} must be a valid HTTPS URL")
