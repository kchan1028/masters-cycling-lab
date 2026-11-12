import hashlib
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

KEY_PATTERN = re.compile(r"[0-9a-f]{32}")
READ_SIZE = 1024 * 1024


@dataclass(frozen=True)
class StoredFile:
    key: str
    sha256: str
    byte_size: int


class FileTooLarge(Exception):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"File is larger than {max_bytes} bytes")
        self.max_bytes = max_bytes


class LocalFileStorage:
    """Stores PDFs on local disk under generated keys. Callers never choose a file name or path."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, source: BinaryIO, max_bytes: int) -> StoredFile:
        """Copy `source` into storage, hashing as it goes. Nothing is left behind if this fails."""
        tmp_dir = self.root / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0

        with tempfile.NamedTemporaryFile(dir=tmp_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                while block := source.read(READ_SIZE):
                    size += len(block)
                    if size > max_bytes:
                        raise FileTooLarge(max_bytes)
                    digest.update(block)
                    tmp.write(block)
                tmp.flush()
                os.fsync(tmp.fileno())
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise

        key = uuid.uuid4().hex
        final_path = self.path(key)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        # Same file system, so the rename is atomic: readers see the whole file or nothing.
        os.replace(tmp_path, final_path)
        return StoredFile(key=key, sha256=digest.hexdigest(), byte_size=size)

    def path(self, key: str) -> Path:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("Not a valid storage key")
        return self.root / "files" / key[:2] / f"{key}.pdf"

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def remove_stale_temp_files(self, older_than_seconds: float = 3600) -> int:
        """Delete partial uploads left behind by a process that was killed mid-write."""
        tmp_dir = self.root / "tmp"
        if not tmp_dir.is_dir():
            return 0
        cutoff = time.time() - older_than_seconds
        removed = 0
        for path in tmp_dir.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def is_writable(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=self.root):
                return True
        except OSError:
            return False
