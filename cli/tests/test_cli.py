from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import click.testing
import pytest
import responses

from homeshare_cli.main import cli

from conftest import make_config, write_config


@pytest.fixture()
def runner(tmp_path: Path) -> click.testing.CliRunner:
    return click.testing.CliRunner(env={"XDG_CONFIG_HOME": str(tmp_path)})


@pytest.fixture()
def mock_keyring() -> Generator[dict[str, str], None, None]:
    store: dict[str, str] = {}

    def get_password(_service: str, username: str) -> str | None:
        return store.get(username)

    def set_password(_service: str, username: str, password: str) -> None:
        store[username] = password

    def delete_password(_service: str, username: str) -> None:
        store.pop(username, None)

    with (
        patch("homeshare_cli.config.keyring.get_password", side_effect=get_password),
        patch("homeshare_cli.config.keyring.set_password", side_effect=set_password),
        patch(
            "homeshare_cli.config.keyring.delete_password", side_effect=delete_password
        ),
    ):
        yield store


BASE_URL = "https://homeshare.example.com"


class TestLogin:
    def test_success(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
    ) -> None:
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, f"{BASE_URL}/api/me", json={"sub": "u"}, status=200)
            result = runner.invoke(
                cli, ["login", BASE_URL, "mysrv"], input="hs_testtoken\n"
            )
        assert result.exit_code == 0, result.output
        assert "Logged in" in result.output
        assert mock_keyring.get("mysrv") == "hs_testtoken"

    def test_invalid_token(
        self,
        runner: click.testing.CliRunner,
    ) -> None:
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{BASE_URL}/api/me",
                json={"error": "unauthorized"},
                status=401,
            )
            result = runner.invoke(cli, ["login", BASE_URL, "mysrv"], input="hs_bad\n")
        assert result.exit_code == 1, result.output
        assert "failed" in result.output.lower()

    def test_overwrites_existing_server(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": "https://old.example.com"}))
        mock_keyring["mysrv"] = "hs_oldtoken"
        new_url = "https://new.example.com"
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, f"{new_url}/api/me", json={"sub": "u"}, status=200)
            result = runner.invoke(
                cli, ["login", new_url, "mysrv"], input="hs_newtoken\n"
            )
        assert result.exit_code == 0, result.output
        assert mock_keyring.get("mysrv") == "hs_newtoken"


class TestLogout:
    def test_single_server(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0, result.output
        assert "Logged out" in result.output
        assert "mysrv" not in mock_keyring

    def test_named_server(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(
            tmp_path,
            make_config({"srv1": BASE_URL, "srv2": "https://other.example.com"}),
        )
        mock_keyring["srv1"] = "hs_t1"
        mock_keyring["srv2"] = "hs_t2"
        result = runner.invoke(cli, ["--server", "srv1", "logout"])
        assert result.exit_code == 0, result.output
        assert "srv1" not in mock_keyring

    def test_no_servers(
        self,
        runner: click.testing.CliRunner,
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({}))
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code != 0

    def test_no_token_in_keyring(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],  # noqa: ARG002 - activates keyring patch
        tmp_path: Path,
    ) -> None:
        # Token absent from keyring: logout should still succeed and remove the
        # server from config (delete_token silently ignores PasswordDeleteError).
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code == 0, result.output
        assert "Logged out" in result.output


class TestUpload:
    def test_success(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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

    def test_with_expiry(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = runner.invoke(cli, ["upload", str(f), "--expiry", "banana"])
        assert result.exit_code != 0
        assert "invalid expiry" in result.output.lower()

    def test_no_token(
        self,
        runner: click.testing.CliRunner,
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = runner.invoke(cli, ["upload", str(f)])
        assert result.exit_code != 0


class TestDelete:
    def test_delete_share(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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

    def test_not_found(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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
    def test_success(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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

    def test_empty(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(tmp_path, make_config({"mysrv": BASE_URL}))
        mock_keyring["mysrv"] = "hs_token"
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

    def test_get_token_falls_back_to_keyring(self) -> None:
        from homeshare_cli.config import ServerConfig, get_token

        srv = ServerConfig(name="srv", url="https://example.com")
        with patch(
            "homeshare_cli.config.keyring.get_password", return_value="hs_kr"
        ) as mock_get:
            result = get_token(srv)
        mock_get.assert_called_once_with("homeshare", "srv")
        assert result == "hs_kr"

    def test_set_token_noop_when_token_file_set(self, tmp_path: Path) -> None:
        from homeshare_cli.config import ServerConfig, set_token

        srv = ServerConfig(
            name="srv", url="https://example.com", token_file=tmp_path / "token"
        )
        with patch("homeshare_cli.config.keyring.set_password") as mock_set:
            set_token(srv, "hs_tok")
        mock_set.assert_not_called()

    def test_delete_token_raises_when_token_file_set(self, tmp_path: Path) -> None:
        from homeshare_cli.config import ServerConfig, delete_token

        srv = ServerConfig(
            name="srv", url="https://example.com", token_file=tmp_path / "token"
        )
        with pytest.raises(ValueError, match="token file"):
            delete_token(srv)

    def test_upload_with_token_file(
        self,
        runner: click.testing.CliRunner,
        tmp_path: Path,
    ) -> None:
        token_file = tmp_path / "mytoken"
        token_file.write_text("hs_filetoken\n")
        token_file.chmod(0o600)
        cfg = make_config({"mysrv": BASE_URL})
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
        cfg = make_config({"mysrv": BASE_URL})
        cfg.servers["mysrv"].token_file = tmp_path / "nonexistent"
        write_config(tmp_path, cfg)
        f = tmp_path / "upload.txt"
        f.write_text("data")
        result = runner.invoke(cli, ["upload", str(f)])
        assert result.exit_code != 0
        assert "Cannot read token file" in result.output

    def test_logout_raises_for_token_file_server(
        self,
        runner: click.testing.CliRunner,
        tmp_path: Path,
    ) -> None:
        token_file = tmp_path / "mytoken"
        token_file.write_text("hs_filetoken\n")
        cfg = make_config({"mysrv": BASE_URL})
        cfg.servers["mysrv"].token_file = token_file
        write_config(tmp_path, cfg)
        result = runner.invoke(cli, ["logout"])
        assert result.exit_code != 0
        assert "token file" in result.output.lower()

    def test_multiple_servers_requires_flag(
        self,
        runner: click.testing.CliRunner,
        mock_keyring: dict[str, str],
        tmp_path: Path,
    ) -> None:
        write_config(
            tmp_path,
            make_config({"srv1": BASE_URL, "srv2": "https://other.example.com"}),
        )
        mock_keyring["srv1"] = "hs_t1"
        mock_keyring["srv2"] = "hs_t2"
        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0
        assert (
            "multiple servers" in result.output.lower() or "--server" in result.output
        )

    def test_no_servers(
        self,
        runner: click.testing.CliRunner,
    ) -> None:
        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0
        assert "no servers" in result.output.lower() or "login" in result.output.lower()
