from pathlib import Path

import itertools
import pytest
import responses

from homeshare_cli.client import ClientError, HomeshareClient


@pytest.fixture()
def base_url() -> str:
    return "https://homeshare.example.com"


@pytest.fixture()
def token() -> str:
    return "hs_testtoken123"


@pytest.fixture()
def client(base_url: str, token: str) -> HomeshareClient:
    return HomeshareClient(base_url=base_url, token=token)


class TestValidateToken:
    def test_valid(self, client: HomeshareClient, base_url: str) -> None:
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, f"{base_url}/api/me", json={"sub": "u"}, status=200)
            assert client.validate_token() is True

    def test_invalid(self, client: HomeshareClient, base_url: str) -> None:
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{base_url}/api/me",
                json={"error": "unauthorized"},
                status=401,
            )
            assert client.validate_token() is False


class TestUpload:
    def test_success(
        self, client: HomeshareClient, base_url: str, tmp_path: Path
    ) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        expected = {"share_id": "abc-123", "link_id": "def-456"}
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST, f"{base_url}/api/shares", json=expected, status=201
            )
            result = client.upload(f)
        assert result == expected

    def test_with_expiry(
        self, client: HomeshareClient, base_url: str, tmp_path: Path
    ) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        expected = {"share_id": "1", "link_id": "2"}
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                f"{base_url}/api/shares",
                json=expected,
                status=201,
            )
            result = client.upload(f, expires_in=86400)
            body = rsps.calls[0].request.body
            assert isinstance(body, bytes)
            assert b"expires_in" in body
            assert b"86400" in body
        assert result == expected

    def test_failure(
        self, client: HomeshareClient, base_url: str, tmp_path: Path
    ) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                f"{base_url}/api/shares",
                json={"error": "unauthorized"},
                status=401,
            )
            with pytest.raises(ClientError) as exc_info:
                client.upload(f)
            assert exc_info.value.status_code == 401

    def test_progress_callback(
        self, client: HomeshareClient, base_url: str, tmp_path: Path
    ) -> None:
        f = tmp_path / "test.bin"
        payload = b"x" * 65536
        f.write_bytes(payload)
        seen: list[tuple[int, int]] = []

        def on_progress(bytes_read: int, total: int) -> None:
            seen.append((bytes_read, total))

        expected = {"share_id": "abc", "link_id": "def"}
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST, f"{base_url}/api/shares", json=expected, status=201
            )
            result = client.upload(f, on_progress=on_progress)
        assert result == expected
        assert seen, "progress callback was never invoked"
        # `responses` reads the streamed body in one go, so at least the final
        # call must report completion with matching read/total values.
        assert seen[-1][0] == seen[-1][1]
        # total covers the file plus multipart framing, so it exceeds the file.
        assert seen[-1][1] > len(payload)
        # bytes_read must be monotonically non-decreasing.
        assert all(a[0] <= b[0] for a, b in itertools.pairwise(seen))

    def test_progress_callback_default_none(
        self, client: HomeshareClient, base_url: str, tmp_path: Path
    ) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello")
        expected = {"share_id": "abc", "link_id": "def"}
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST, f"{base_url}/api/shares", json=expected, status=201
            )
            result = client.upload(f)
        assert result == expected


class TestListShares:
    def test_success(self, client: HomeshareClient, base_url: str) -> None:
        shares = [
            {
                "share_id": "1",
                "filename": "a.txt",
                "links": [],
                "created_at": "2025-01-01T00:00:00",
            }
        ]
        with responses.RequestsMock() as rsps:
            rsps.add(responses.GET, f"{base_url}/api/shares", json=shares, status=200)
            result = client.list_shares()
        assert result == shares

    def test_failure(self, client: HomeshareClient, base_url: str) -> None:
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                f"{base_url}/api/shares",
                json={"error": "unauthorized"},
                status=401,
            )
            with pytest.raises(ClientError) as exc_info:
                client.list_shares()
            assert exc_info.value.status_code == 401


class TestDeleteShare:
    def test_success(self, client: HomeshareClient, base_url: str) -> None:
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.DELETE,
                f"{base_url}/api/shares/1",
                json={"status": "deleted"},
                status=200,
            )
            data, status = client.delete_share(1)
        assert data["status"] == "deleted"
        assert status == 200


class TestDeleteLink:
    def test_success(self, client: HomeshareClient, base_url: str) -> None:
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.DELETE,
                f"{base_url}/api/links/abc",
                json={"status": "deleted"},
                status=200,
            )
            data, status = client.delete_link("abc")
        assert data["status"] == "deleted"
        assert status == 200
