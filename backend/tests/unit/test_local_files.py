import hashlib
import io
from pathlib import Path

import pytest

from masters_cycling_lab.infrastructure.storage.local_files import FileTooLarge, LocalFileStorage


def files_under(path: Path) -> list[Path]:
    return [p for p in path.rglob("*") if p.is_file()]


def test_save_hashes_and_stores_under_a_generated_key(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b"%PDF-1.7 example" * 1000

    stored = storage.save(io.BytesIO(content), max_bytes=1_000_000)

    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert stored.byte_size == len(content)
    assert storage.path(stored.key).read_bytes() == content
    assert files_under(tmp_path / "tmp") == []


def test_too_large_file_leaves_nothing_behind(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)

    with pytest.raises(FileTooLarge):
        storage.save(io.BytesIO(b"x" * 101), max_bytes=100)

    assert files_under(tmp_path) == []


def test_same_content_gets_a_new_key_each_time(tmp_path: Path) -> None:
    # Duplicate detection is the caller's job (by sha256); storage never overwrites a file.
    storage = LocalFileStorage(tmp_path)
    first = storage.save(io.BytesIO(b"same"), max_bytes=100)
    second = storage.save(io.BytesIO(b"same"), max_bytes=100)
    assert first.key != second.key
    assert first.sha256 == second.sha256


@pytest.mark.parametrize("key", ["../../etc/passwd", "ABCDEF0123456789ABCDEF0123456789", "short", "a" * 32 + "/x", ""])
def test_keys_that_are_not_generated_are_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        LocalFileStorage(tmp_path).path(key)


def test_delete_removes_the_file_and_tolerates_missing_files(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    stored = storage.save(io.BytesIO(b"data"), max_bytes=100)

    storage.delete(stored.key)
    storage.delete(stored.key)

    assert not storage.path(stored.key).exists()


def test_is_writable(tmp_path: Path) -> None:
    assert LocalFileStorage(tmp_path / "new-dir").is_writable()

    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    assert not LocalFileStorage(blocker / "storage").is_writable()
