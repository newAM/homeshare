from dataclasses import dataclass
from pathlib import Path
import shlex

import click
from rich.console import Console
from rich.table import Table

from homeshare_cli.client import ClientError, HomeshareClient
from homeshare_cli.config import (
    get_token,
    resolve_server_name,
)
from homeshare_common.duration import parse_duration

console = Console()


@dataclass
class ResolvedServer:
    client: HomeshareClient
    url: str
    name: str


def _resolve_server(server_name: str | None) -> ResolvedServer:
    """Resolve server config and return a ready-to-use ResolvedServer."""
    try:
        _cfg, srv = resolve_server_name(server_name)
    except ValueError as e:
        raise click.ClickException(str(e)) from None
    try:
        token = get_token(srv)
    except ValueError as e:
        raise click.ClickException(str(e)) from None
    return ResolvedServer(
        client=HomeshareClient(base_url=srv.url, token=token),
        url=srv.url,
        name=srv.name,
    )


@click.group()
@click.option("--server", "-s", default=None, help="Server name from config.")
@click.pass_context
def cli(ctx: click.Context, server: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["server_name"] = server


@cli.command(help="Upload a file to the server.")
@click.argument("file_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--expiry", "-e", default=None, help="Expiry duration (e.g. '7 days', '2h')."
)
@click.pass_context
def upload(ctx: click.Context, file_path: Path, expiry: str | None) -> None:
    server_name: str | None = ctx.obj.get("server_name")
    resolved = _resolve_server(server_name)
    expires_in = None
    if expiry is not None:
        try:
            expires_in = parse_duration(expiry)
        except ValueError as e:
            raise click.ClickException(f"Invalid expiry value: {e}") from None
    try:
        result = resolved.client.upload(file_path, expires_in=expires_in)
    except ClientError as e:
        raise click.ClickException(f"Upload failed: {e.message}") from None
    base = resolved.url.rstrip("/")
    link_id = result["link_id"]
    share_id = result["share_id"]
    download_url = f"{base}/links/{link_id}/download"
    console.print(f"[green]Uploaded {file_path.name}[/green]")
    console.print(f"  Download URL: {download_url}", no_wrap=True)
    console.print(
        f"  curl: curl -o {shlex.quote(str(file_path.name))} '{download_url}'",
        no_wrap=True,
    )
    console.print(f"  Delete: homeshare delete {share_id}", no_wrap=True)


@cli.command(help="Delete a share or link by ID.")
@click.argument("share_id", required=True)
@click.pass_context
def delete(ctx: click.Context, share_id: str) -> None:
    server_name: str | None = ctx.obj.get("server_name")
    resolved = _resolve_server(server_name)
    try:
        _data, status = resolved.client.delete_share(share_id)
        if status == 404:
            _data, status = resolved.client.delete_link(share_id)
            if status == 404:
                raise click.ClickException(
                    f"ID {share_id!r} not found as a share or link."
                )
            console.print(f"[green]Deleted link {share_id}[/green]")
        else:
            console.print(f"[green]Deleted share {share_id}[/green]")
    except ClientError as e:
        raise click.ClickException(f"Delete failed: {e.message}") from None


@cli.command("list", help="List uploaded shares.")
@click.pass_context
def list_shares(ctx: click.Context) -> None:
    server_name: str | None = ctx.obj.get("server_name")
    resolved = _resolve_server(server_name)
    try:
        shares = resolved.client.list_shares()
    except ClientError as e:
        raise click.ClickException(f"Failed to list shares: {e.message}") from None
    if not shares:
        console.print("No shares.")
        return
    table = Table()
    table.add_column("Filename")
    table.add_column("Share ID")
    table.add_column("Links")
    table.add_column("Created")
    for s in shares:
        table.add_row(
            s.get("filename", ""),
            str(s.get("share_id", "")),
            str(len(s.get("links", []))),  # type: ignore[arg-type]
            s.get("created_at", ""),
        )
    console.print(table)
