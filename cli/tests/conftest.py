from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from homeshare_cli.config import AppConfig, ServerConfig, save_config


def make_config(
    servers: dict[str, str] | None = None,
    token_dir: Path | None = None,
) -> AppConfig:
    cfg = AppConfig()
    for name, url in (servers or {}).items():
        assert token_dir is not None, "token_dir is required when servers are provided"
        token_file = token_dir / f"{name}.token"
        token_file.write_text(f"hs_{name}_token\n")
        token_file.chmod(0o600)
        cfg.servers[name] = ServerConfig(name=name, url=url, token_file=token_file)
    return cfg


def write_config(tmp_path: Path, cfg: AppConfig) -> None:
    config_path = tmp_path / "homeshare" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with patch("homeshare_cli.config.get_config_path", return_value=config_path):
        save_config(cfg)
