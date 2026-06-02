import io
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from homeshare.storage import cleanup_orphans, get_file, save_file


def test_save_file_creates_file(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    file = FileStorage(stream=io.BytesIO(b"hello world"), filename="test.txt")

    stored_path = save_file(file, upload_dir)

    assert Path(stored_path).exists()
    assert Path(stored_path).read_bytes() == b"hello world"


def test_save_file_creates_upload_dir(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    file = FileStorage(stream=io.BytesIO(b"data"), filename="test.txt")

    save_file(file, upload_dir)

    assert upload_dir.exists()


def test_save_file_raises_for_missing_parent(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads" / "nested"
    file = FileStorage(stream=io.BytesIO(b"data"), filename="test.txt")

    with pytest.raises(FileNotFoundError):
        save_file(file, upload_dir)


def test_save_file_unique_paths(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    file_a = FileStorage(stream=io.BytesIO(b"a"), filename="test.txt")
    file_b = FileStorage(stream=io.BytesIO(b"b"), filename="test.txt")

    path_a = save_file(file_a, upload_dir)
    path_b = save_file(file_b, upload_dir)

    assert path_a != path_b


def test_get_file_returns_path(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    file = FileStorage(stream=io.BytesIO(b"content"), filename="test.txt")
    stored_path = save_file(file, upload_dir)

    result = get_file(stored_path, upload_dir)

    assert result == Path(stored_path)
    assert result.read_bytes() == b"content"


def test_get_file_raises_for_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        get_file(tmp_path / "nonexistent", tmp_path)


def test_cleanup_orphans_deletes_unknown_files(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()

    known_file = upload_dir / "known123"
    known_file.write_bytes(b"keep me")
    orphan_file = upload_dir / "orphan456"
    orphan_file.write_bytes(b"remove me")

    count = cleanup_orphans(upload_dir, {str(known_file)})

    assert count == 1
    assert known_file.exists()
    assert not orphan_file.exists()


def test_cleanup_orphans_keeps_all_when_no_orphans(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()

    file_a = upload_dir / "aaa"
    file_a.write_bytes(b"a")
    file_b = upload_dir / "bbb"
    file_b.write_bytes(b"b")

    count = cleanup_orphans(upload_dir, {str(file_a), str(file_b)})

    assert count == 0
    assert file_a.exists()
    assert file_b.exists()


def test_cleanup_orphans_returns_zero_for_missing_dir(tmp_path: Path) -> None:
    count = cleanup_orphans(tmp_path / "nonexistent", set())
    assert count == 0


def test_cleanup_orphans_ignores_subdirectories(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    sub = upload_dir / "subdir"
    sub.mkdir()

    count = cleanup_orphans(upload_dir, set())
    assert count == 0
    assert sub.exists()
