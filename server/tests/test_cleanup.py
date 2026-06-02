from pathlib import Path

from flask import Flask
from flask.testing import FlaskCliRunner

from homeshare.models import Share, db


def test_cleanup_command_removes_orphans(app: Flask) -> None:
    upload_dir = Path(app.config["UPLOAD_DIR"])

    orphan = upload_dir / "orphan_file"
    orphan.write_bytes(b"leftover")

    runner: FlaskCliRunner = app.test_cli_runner()
    result = runner.invoke(args="cleanup")

    assert result.exit_code == 0
    assert "Deleted 1 orphan file(s)" in result.output
    assert not orphan.exists()


def test_cleanup_command_no_orphans(app: Flask) -> None:
    runner: FlaskCliRunner = app.test_cli_runner()
    result = runner.invoke(args="cleanup")

    assert result.exit_code == 0
    assert "Deleted 0 orphan file(s)" in result.output


def test_cleanup_command_preserves_known_files(app: Flask) -> None:
    upload_dir = Path(app.config["UPLOAD_DIR"])

    stored_path = str(upload_dir / "known_file")
    Path(stored_path).write_bytes(b"keep")

    with app.app_context():
        share = Share(
            filename="test.txt",
            stored_path=stored_path,
            owner="test-user-sub",
        )
        db.session.add(share)
        db.session.commit()

    runner: FlaskCliRunner = app.test_cli_runner()
    result = runner.invoke(args="cleanup")

    assert result.exit_code == 0
    assert "Deleted 0 orphan file(s)" in result.output
    assert Path(stored_path).exists()
