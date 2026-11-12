"""The research corpus: a version-controlled manifest of papers, and the PDFs it points to.

The manifest (research/corpus/manifest.jsonl) is the source of truth. PDFs are kept out of git; `download` fetches
them from the recorded open-access source and `verify` proves the local files are the ones the manifest describes.
"""

import hashlib
import json
import re
import unicodedata
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from masters_cycling_lab.application import documents
from masters_cycling_lab.application.documents import DocumentView
from masters_cycling_lab.config import REPO_ROOT, Settings
from masters_cycling_lab.infrastructure.db.models import Document
from masters_cycling_lab.infrastructure.pdf.pymupdf_extractor import first_pages_text
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage

DEFAULT_MANIFEST = REPO_ROOT / "research" / "corpus" / "manifest.jsonl"
SHA256 = r"^[0-9a-f]{64}$"

PopulationRelevance = Literal[
    "masters_cyclists",  # the study population is masters cyclists
    "age_comparison_cyclists",  # older and younger cyclists compared directly
    "masters_athletes_mixed_sports",  # masters athletes, cyclists among other sports or unspecified
    "masters_athletes_other_sport",  # masters athletes in another sport only (e.g. running)
    "adult_cyclists",  # cyclists, not selected for age
    "endurance_athletes_mixed",  # endurance athletes of several sports, not selected for age
]


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: str = Field(pattern=r"^mcl-\d{3}$")
    title: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1)
    year: int = Field(ge=1900, le=2100)
    citation: str
    doi: str | None = Field(default=None, pattern=r"^10\.\d{4,9}/\S+$")
    pmcid: str | None = Field(default=None, pattern=r"^PMC\d+$")
    pmid: int | None = None
    landing_page_url: str = Field(pattern=r"^https://")
    download_url: str | None = Field(default=None, pattern=r"^https://")
    download_source: str
    license: str
    license_source: str
    access: Literal["open_access", "user_provided", "restricted"]
    redistribution: str
    # False means only the abstract is available. Such entries must never be presented as full-text evidence.
    full_text: bool
    retracted_at_acquisition: bool
    file: str
    sha256: str = Field(pattern=SHA256)
    bytes: int = Field(gt=0)
    acquired_on: date
    bibliographic_source: str
    population_relevance: PopulationRelevance
    population: str
    age_range: str
    sport: str
    study_design: str
    topics: list[str]
    description_source: str
    description_review_status: Literal["provisional", "reviewed"]


class ManifestError(Exception):
    pass


def load_manifest(path: Path) -> list[ManifestEntry]:
    entries: list[ManifestEntry] = []
    problems: list[str] = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(ManifestEntry.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            problems.append(f"line {number}: {exc}")
    for field in ("corpus_id", "sha256", "pmcid", "doi", "file"):
        values = [getattr(entry, field) for entry in entries if getattr(entry, field) is not None]
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            problems.append(f"duplicate {field}: {', '.join(map(str, duplicates))}")
    if problems:
        raise ManifestError("\n".join(problems))
    return entries


def local_path(manifest: Path, entry: ManifestEntry) -> Path:
    """Where the entry's PDF lives, relative to the manifest. Refuses paths that leave the corpus folder."""
    root = manifest.parent.resolve()
    path = (root / entry.file).resolve()
    if not path.is_relative_to(root):
        raise ManifestError(f"{entry.corpus_id}: file {entry.file!r} points outside {root}")
    return path


@dataclass(frozen=True)
class FileCheck:
    corpus_id: str
    problems: list[str]


def verify_files(manifest: Path, entries: list[ManifestEntry]) -> list[FileCheck]:
    """Check each PDF exists, matches its recorded size and SHA-256, and shows its recorded title on page 1 or 2."""
    checks = []
    for entry in entries:
        problems = []
        path = local_path(manifest, entry)
        if not path.is_file():
            problems.append(f"missing {entry.file} (run `make corpus-download`)")
        else:
            content = path.read_bytes()
            if len(content) != entry.bytes or hashlib.sha256(content).hexdigest() != entry.sha256:
                problems.append("file differs from the manifest (size or SHA-256)")
            elif normalize(entry.title) not in normalize(first_pages_text(path)):
                problems.append("recorded title not found on the first two pages")
        if entry.retracted_at_acquisition:
            problems.append("marked as retracted")
        checks.append(FileCheck(entry.corpus_id, problems))
    return checks


def download_missing(
    manifest: Path, entries: list[ManifestEntry], fetch: Callable[[str], bytes] | None = None
) -> list[tuple[str, str]]:
    """Fetch PDFs that are missing or wrong, from each entry's recorded open-access URL. Never keeps a file whose
    SHA-256 differs from the manifest."""
    fetch = fetch or fetch_url
    results = []
    for entry in entries:
        path = local_path(manifest, entry)
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry.sha256:
            results.append((entry.corpus_id, "already present"))
            continue
        if entry.download_url is None:
            results.append((entry.corpus_id, "no download URL; add the file by hand"))
            continue
        content = fetch(entry.download_url)
        if hashlib.sha256(content).hexdigest() != entry.sha256:
            results.append((entry.corpus_id, "downloaded file does not match the manifest SHA-256; not saved"))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(content)
        tmp.replace(path)
        results.append((entry.corpus_id, "downloaded"))
    return results


def ingest(
    session: Session, storage: LocalFileStorage, settings: Settings, manifest: Path, entries: list[ManifestEntry]
) -> list[tuple[ManifestEntry, DocumentView, bool]]:
    """Upload each PDF (duplicates are skipped by hash) and set its metadata from the manifest."""
    results = []
    for entry in entries:
        with local_path(manifest, entry).open("rb") as file:
            view, duplicate = documents.upload_document(session, storage, settings, Path(entry.file).name, file, {})
        view = documents.update_metadata(
            session, view.document.id, manifest_metadata(entry), source="manifest_verified"
        )
        results.append((entry, view, duplicate))
    return results


def index_status(session: Session, entries: list[ManifestEntry]) -> dict[str, str]:
    """For each entry: not uploaded, uploaded but not searchable yet, or searchable."""
    found = {
        document.sha256: document
        for document in session.scalars(
            select(Document).where(
                Document.sha256.in_([entry.sha256 for entry in entries]), Document.deleted_at.is_(None)
            )
        )
    }
    status = {}
    for entry in entries:
        document = found.get(entry.sha256)
        if document is None:
            status[entry.corpus_id] = "not uploaded"
        elif document.active_index_version_id is None:
            status[entry.corpus_id] = "uploaded, not searchable yet"
        else:
            status[entry.corpus_id] = "searchable"
    return status


def manifest_metadata(entry: ManifestEntry) -> dict[str, object]:
    return {
        "title": entry.title,
        "authors": entry.authors,
        "publication_year": entry.year,
        "doi": entry.doi,
        "source_url": entry.landing_page_url,
        "license": entry.license,
        "access_status": entry.access,
    }


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", text).lower()).strip()


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "masters-cycling-lab corpus download"})
    with urllib.request.urlopen(request, timeout=120) as response:
        content: bytes = response.read()
        return content
