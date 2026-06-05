from pathlib import Path

import click.testing
import pytest
import responses

from homeshare_cli.main import cli

from conftest import make_config, write_config


@pytest.fixture()
def runner(tmp_path: Path) -> click.testing.CliRunner:
    return click.testing.CliRunner(env={"XDG_CONFIG_HOME": str(tmp_path)})


BASE_URL = "https://homeshare.example.com"


def _setup_server(tmp_path: Path, name: str = "mysrv", url: str = BASE_URL) -> None:
    cfg = make_config({name: url}, token_dir=tmp_path)
    write_config(tmp_path, cfg)


class TestUpload:
    def test_success(self, runner: click.testing.CliRunner, tmp_path: Path) -> None:
        _setup_server(tmp_path)
        f = tmp_path / "test.txt"
        f.write_text("hello")
        expected = {"share_id": "abc-123", "link_id": "def-456"}
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST, f"{BASE_URL}/api/shares", json=expected, status=201
            )
            result = runner.invoke(cli, ["upload", str(f)])
        assert result.exit_code == 0, result.output
        assert "Uploaded test.txt" in result.output
        assert "/links/def-456/download" in result.output
        assert "homeshare delete abc-123" in result.output

    def test_with_expiry(self, runner: click.testing.CliRunner, tmp_path: Path) -> None:
        _setup_server(tmp_path)
        f = tmp_path / "test.txt"
        f.write_text("hello")
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                f"{BASE_URL}/api/shares",
                json={"share_id": "1", "link_id": "2"},
                status=201,
            )
            result = runner.invoke(cli, ["upload", str(f), "--expiry", "7 days"])
        assert result.exit_code == 0, result.output

    def test_invalid_expiry(
        self, runner: click.testing.CliRunner, tmp_path: Path
    ) -> None:
        _setup_server(tmp_path)
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = runner.invoke(cli, ["upload", str(f), "--expiry", "banana"])
        assert result.exit_code != 0
        assert "invalid expiry" in result.output.lower()

    def test_no_token(self, runner: click.testing.CliRunner, tmp_path: Path) -> None:
        cfg = make_config({"mysrv": BASE_URL}, token_dir=tmp_path)
        cfg.servers["mysrv"].token_file = tmp_path / "nonexistent"
        write_config(tmp_path, cfg)
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = runner.invoke(cli, ["upload", str(f)])
        assert result.exit_code != 0


class TestDelete:
    def test_delete_share(
        self, runner: click.testing.CliRunner, tmp_path: Path
    ) -> None:
        _setup_server(tmp_path)
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.DELETE,
                f"{BASE_URL}/api/shares/1",
                json={"status": "deleted"},
                status=200,
            )
            result = runner.invoke(cli, ["delete", "1"])
        assert result.exit_code == 0, result.output
        assert "Deleted share 1" in result.output

    def test_delete_link_fallback(
        self, runner: click.testing.CliRunner, tmp_path: Path
    ) -> None:
        _setup_server(tmp_path)
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.DELETE,
                f"{BASE_URL}/api/shares/abc",
                json={"error": "not found"},
                status=404,
            )
            rsps.add(
                responses.DELETE,
                f"{BASE_URL}/api/links/abc",
                json={"status": "deleted"},
                status=200,
            )
            result = runner.invoke(cli, ["delete", "abc"])
        assert result.exit_code == 0, result.output
        assert "Deleted link abc" in result.output

    def test_not_found(self, runner: click.testing.CliRunner, tmp_path: Path) -> None:
        _setup_server(tmp_path)
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.DELETE,
                f"{BASE_URL}/api/shares/xyz",
                json={"error": "not found"},
                status=404,
            )
            rsps.add(
                responses.DELETE,
                f"{BASE_URL}/api/links/xyz",
                json={"error": "not found"},
                status=404,
            )
            result = runner.invoke(cli, ["delete", "xyz"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_server_error(
        self, runner: click.testing.CliRunner, tmp_path: Path
    ) -> None:
        _setup_server(tmp_path)
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.DELETE,
                f"{BASE_URL}/api/shares/1",
                body="Internal Server Error",
                status=500,
            )
            result = runner.invoke(cli, ["delete", "1"])
        assert result.exit_code != 0
        assert "Delete failed" in result.output


class TestList:
    def test_success(self, runner: click.testing.CliRunner, tmp_path: Path) -> None:
        _setup_server(tmp_path)
        shares = [
            {
                "share_id": "1",
                "filename": "a.txt",
                "links": [{"link_id": "x"}],
                "created_at": "2025-01-01T00:00:00",
            },
        ]
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, f"{BASE_URL}/api/shares", json=shares, status=200)
            result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0, result.output
        assert "a.txt" in result.output

    def test_empty(self, runner: click.testing.CliRunner, tmp_path: Path) -> None:
        _setup_server(tmp_path)
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, f"{BASE_URL}/api/shares", json=[], status=200)
            result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0, result.output
        assert "No shares" in result.output


class TestTokenFile:
    def test_get_token_reads_file(self, tmp_path: Path) -> None:
        from homeshare_cli.config import ServerConfig, get_token

        token_file = tmp_path / "token"
        token_file.write_text("hs_filetoken\n")
        token_file.chmod(0o600)
        srv = ServerConfig(name="srv", url="https://example.com", token_file=token_file)
        assert get_token(srv) == "hs_filetoken"

    def test_get_token_missing_file_raises(self, tmp_path: Path) -> None:
        from homeshare_cli.config import ServerConfig, get_token

        srv = ServerConfig(
            name="srv",
            url="https://example.com",
            token_file=tmp_path / "nonexistent",
        )
        with pytest.raises(ValueError, match="Cannot read token file"):
            get_token(srv)

    def test_get_token_rejects_loose_permissions(self, tmp_path: Path) -> None:
        from homeshare_cli.config import ServerConfig, get_token

        token_file = tmp_path / "token"
        token_file.write_text("hs_filetoken\n")
        token_file.chmod(0o644)
        srv = ServerConfig(name="srv", url="https://example.com", token_file=token_file)
        with pytest.raises(ValueError, match="0o644"):
            get_token(srv)

    def test_get_token_no_warning_on_strict_permissions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from homeshare_cli.config import ServerConfig, get_token

        token_file = tmp_path / "token"
        token_file.write_text("hs_filetoken\n")
        token_file.chmod(0o600)
        srv = ServerConfig(name="srv", url="https://example.com", token_file=token_file)
        assert get_token(srv) == "hs_filetoken"
        assert capsys.readouterr().err == ""

    def test_upload_with_token_file(
        self,
        runner: click.testing.CliRunner,
        tmp_path: Path,
    ) -> None:
        token_file = tmp_path / "mytoken"
        token_file.write_text("hs_filetoken\n")
        token_file.chmod(0o600)
        cfg = make_config({"mysrv": BASE_URL}, token_dir=tmp_path)
        cfg.servers["mysrv"].token_file = token_file
        write_config(tmp_path, cfg)
        f = tmp_path / "upload.txt"
        f.write_text("data")
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                f"{BASE_URL}/api/shares",
                json={"share_id": "s1", "link_id": "l1"},
                status=201,
            )
            result = runner.invoke(cli, ["upload", str(f)])
        assert result.exit_code == 0, result.output
        assert "Uploaded upload.txt" in result.output

    def test_upload_missing_token_file(
        self,
        runner: click.testing.CliRunner,
        tmp_path: Path,
    ) -> None:
        cfg = make_config({"mysrv": BASE_URL}, token_dir=tmp_path)
        cfg.servers["mysrv"].token_file = tmp_path / "nonexistent"
        write_config(tmp_path, cfg)
        f = tmp_path / "upload.txt"
        f.write_text("data")
        result = runner.invoke(cli, ["upload", str(f)])
        assert result.exit_code != 0
        assert "Cannot read token file" in result.output

    def test_config_missing_token_file_raises(self) -> None:
        from homeshare_cli.config import _parse_config

        toml_text = """
[servers.mysrv]
url = "https://example.com"
"""
        with pytest.raises(ValueError, match="missing required 'token_file'"):
            _parse_config(toml_text)

    def test_multiple_servers_requires_flag(
        self,
        runner: click.testing.CliRunner,
        tmp_path: Path,
    ) -> None:
        cfg = make_config(
            {"srv1": BASE_URL, "srv2": "https://other.example.com"},
            token_dir=tmp_path,
        )
        write_config(tmp_path, cfg)
        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0
        assert (
            "multiple servers" in result.output.lower() or "--server" in result.output
        )

    def test_no_servers(self, runner: click.testing.CliRunner) -> None:
        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0
        assert "no servers" in result.output.lower()
