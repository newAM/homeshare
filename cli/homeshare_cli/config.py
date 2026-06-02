import contextlib
from dataclasses import dataclass, field
from pathlib import Path
import tomllib

import keyring
import keyring.errors
import platformdirs
import tomli_w

SERVICE_NAME = "homeshare"


@dataclass
class ServerConfig:
    name: str
    url: str
    token_file: Path | None = None


@dataclass
class AppConfig:
    servers: dict[str, ServerConfig] = field(default_factory=dict)

    def get_server(self, name: str | None = None) -> ServerConfig:
        if name is not None:
            if name not in self.servers:
                raise ValueError(f"server {name!r} not found in config")
            return self.servers[name]
        if len(self.servers) == 0:
            raise ValueError("no servers configured. Run 'homeshare login' first.")
        if len(self.servers) > 1:
            names = ", ".join(sorted(self.servers))
            raise ValueError(
                f"multiple servers configured ({names}). Use --server to specify."
            )
        return next(iter(self.servers.values()))


def get_config_path() -> Path:
    return (
        platformdirs.user_config_path(SERVICE_NAME, ensure_exists=True) / "config.toml"
    )


def _parse_config(text: str) -> AppConfig:
    data = tomllib.loads(text)
    cfg = AppConfig()
    servers = data.get("servers", {})
    for name, info in servers.items():
        token_file_raw = info.get("token_file")
        token_file = Path(token_file_raw) if token_file_raw is not None else None
        cfg.servers[name] = ServerConfig(
            name=name, url=info["url"], token_file=token_file
        )
    return cfg


def load_config() -> AppConfig:
    path = get_config_path()
    if not path.exists():
        return AppConfig()
    return _parse_config(path.read_text())


def resolve_server_name(server_name: str | None) -> tuple[AppConfig, ServerConfig]:
    """Load config and resolve *server_name* to a ServerConfig.

    Returns (cfg, srv) so callers that need to mutate the config can reuse the
    already-loaded instance.  Raises ValueError (same as AppConfig.get_server)
    when the name cannot be resolved.
    """
    cfg = load_config()
    srv = cfg.get_server(server_name)
    return cfg, srv


def save_config(cfg: AppConfig) -> None:
    path = get_config_path()
    data: dict[str, dict[str, dict[str, str]]] = {"servers": {}}
    for name, server in sorted(cfg.servers.items()):
        entry: dict[str, str] = {"url": server.url}
        if server.token_file is not None:
            entry["token_file"] = str(server.token_file)
        data["servers"][name] = entry
    path.write_text(tomli_w.dumps(data))
    path.chmod(0o600)


def get_token(server: ServerConfig) -> str | None:
    if server.token_file is not None:
        try:
            mode = server.token_file.stat().st_mode & 0o777
            if mode & 0o077:
                raise ValueError(
                    f"Token file {str(server.token_file)!r} has permissions "
                    f"{oct(mode)}; refusing to read. Restrict to 0600."
                )
            token = server.token_file.read_text().strip()
        except OSError as e:
            raise ValueError(
                f"Cannot read token file {server.token_file!r}: {e}"
            ) from e
        return token
    return keyring.get_password(SERVICE_NAME, server.name)


def set_token(server: ServerConfig, token: str) -> None:
    if server.token_file is not None:
        return
    keyring.set_password(SERVICE_NAME, server.name, token)


def delete_token(server: ServerConfig) -> None:
    if server.token_file is not None:
        raise ValueError(
            f"Server {server.name!r} uses a token file ({server.token_file}). "
            "Remove the token file manually; 'logout' only supports keyring configuration."
        )
    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(SERVICE_NAME, server.name)
