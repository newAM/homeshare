from pathlib import Path

from homeshare_cli.config import AppConfig, ServerConfig


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
    lines = ["[servers]"]
    for name, srv in sorted(cfg.servers.items()):
        lines.append("")
        lines.append(f"[servers.{name}]")
        lines.append(f'url = "{srv.url}"')
        lines.append(f'token_file = "{srv.token_file}"')
    config_path.write_text("\n".join(lines) + "\n")
    config_path.chmod(0o600)
