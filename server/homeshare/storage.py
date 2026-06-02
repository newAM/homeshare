import uuid
from pathlib import Path

from werkzeug.datastructures import FileStorage


def save_file(file: FileStorage, upload_dir: str | Path) -> str:
    """Save an uploaded file to disk and return the stored path.

    The file is saved under a UUID-based filename to avoid collisions and
    prevent path traversal attacks from untrusted original filenames.
    """
    dest_dir = Path(upload_dir).resolve()
    dest_dir.mkdir(exist_ok=True)

    stored_name = uuid.uuid4().hex
    stored_path = dest_dir / stored_name
    file.save(stored_path)

    return str(stored_path)


def get_file(stored_path: str | Path, upload_dir: str | Path) -> Path:
    """Return the Path for a stored file, raising errors if missing or outside upload_dir."""
    path = Path(stored_path).resolve()
    base = Path(upload_dir).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"stored path is outside upload directory: {path}")
    if not path.exists():
        raise FileNotFoundError(f"stored file not found: {path}")
    return path


def delete_file(stored_path: str | Path, upload_dir: str | Path) -> None:
    """Delete the file on disk. Silently ignores missing files."""
    path = Path(stored_path).resolve()
    base = Path(upload_dir).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"stored path is outside upload directory: {path}")
    path.unlink(missing_ok=True)


def cleanup_orphans(upload_dir: str | Path, known_paths: set[str]) -> int:
    """Delete files in upload_dir not present in known_paths.

    Returns the number of orphan files removed.
    """
    base = Path(upload_dir).resolve()
    if not base.exists():
        return 0
    known = {Path(p).resolve() for p in known_paths}
    deleted = 0
    for entry in base.iterdir():
        if entry.is_file() and entry not in known:
            entry.unlink(missing_ok=True)
            deleted += 1
    return deleted
