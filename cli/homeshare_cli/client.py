from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

DEFAULT_TIMEOUT = 30


class ClientError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class HomeshareClient:
    base_url: str
    token: str = field(repr=False)
    timeout: int = field(default=DEFAULT_TIMEOUT)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def validate_token(self) -> bool:
        resp = requests.get(
            self._url("/api/me"), headers=self._headers(), timeout=self.timeout
        )
        return resp.status_code == 200

    def upload(self, file_path: Path, expires_in: int | None = None) -> dict[str, Any]:
        data: dict[str, str | int] = {}
        if expires_in is not None:
            data["expires_in"] = str(expires_in)
        with file_path.open("rb") as f:
            resp = requests.post(
                self._url("/api/shares"),
                headers=self._headers(),
                files={"file": (file_path.name, f)},
                data=data,
                timeout=self.timeout,
            )
        if resp.status_code != 201:
            raise ClientError(resp.text, resp.status_code)
        return resp.json()

    def list_shares(self) -> list[dict[str, Any]]:
        resp = requests.get(
            self._url("/api/shares"), headers=self._headers(), timeout=self.timeout
        )
        if resp.status_code != 200:
            raise ClientError(resp.text, resp.status_code)
        return resp.json()

    def _delete(self, path: str) -> tuple[dict[str, Any], int]:
        resp = requests.delete(
            self._url(path), headers=self._headers(), timeout=self.timeout
        )
        if resp.status_code not in (200, 404):
            raise ClientError(resp.text, resp.status_code)
        try:
            return resp.json(), resp.status_code
        except requests.exceptions.JSONDecodeError:
            return {}, resp.status_code

    def delete_share(self, share_id: str | int) -> tuple[dict[str, Any], int]:
        return self._delete(f"/api/shares/{share_id}")

    def delete_link(self, link_id: str) -> tuple[dict[str, Any], int]:
        return self._delete(f"/api/links/{link_id}")
