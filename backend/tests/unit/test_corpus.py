from pathlib import Path

import pytest

from masters_cycling_lab.application import corpus
from masters_cycling_lab.application.corpus import DEFAULT_MANIFEST, ManifestError, load_manifest
from tests.helpers import make_pdf, manifest_entry, write_manifest


def test_the_committed_manifest_is_valid() -> None:
    entries = load_manifest(DEFAULT_MANIFEST)
    assert len(entries) >= 20
    assert all(entry.full_text and entry.license.startswith("CC") for entry in entries)


def test_duplicates_and_bad_fields_are_reported_with_line_numbers(tmp_path: Path) -> None:
    pdf = make_pdf(["Recovery in Masters Cyclists"])
    manifest = write_manifest(
        tmp_path, manifest_entry(pdf), manifest_entry(pdf, corpus_id="mcl-002"), manifest_entry(pdf, year="soon")
    )
    with pytest.raises(ManifestError) as error:
        load_manifest(manifest)
    assert "line 3" in str(error.value)
    assert "duplicate sha256" in str(error.value)


def test_verify_accepts_the_right_file_and_names_every_problem(tmp_path: Path) -> None:
    good = make_pdf(["Recovery in Masters Cyclists\nBody text."])
    wrong_title = make_pdf(["Something else entirely"])
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "paper.pdf").write_bytes(good)
    (tmp_path / "pdfs" / "other.pdf").write_bytes(wrong_title)
    unique = {"doi": None, "pmcid": None}
    manifest = write_manifest(
        tmp_path,
        manifest_entry(good),
        manifest_entry(wrong_title, corpus_id="mcl-002", file="pdfs/other.pdf", **unique),
        manifest_entry(b"%PDF-missing", corpus_id="mcl-003", file="pdfs/missing.pdf", **unique),
    )

    checks = {check.corpus_id: check.problems for check in corpus.verify_files(manifest, load_manifest(manifest))}

    assert checks["mcl-001"] == []
    assert "title not found" in checks["mcl-002"][0]
    assert "missing" in checks["mcl-003"][0]


def test_files_outside_the_corpus_folder_are_refused(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, manifest_entry(b"%PDF-x", file="../../etc/passwd"))
    with pytest.raises(ManifestError, match="outside"):
        corpus.verify_files(manifest, load_manifest(manifest))


def test_download_keeps_only_files_with_the_recorded_hash(tmp_path: Path) -> None:
    real = make_pdf(["Recovery in Masters Cyclists"])
    manifest = write_manifest(
        tmp_path,
        manifest_entry(real),
        manifest_entry(real + b"tampered", corpus_id="mcl-002", file="pdfs/b.pdf", doi=None, pmcid=None),
    )
    entries = load_manifest(manifest)

    outcomes = dict(corpus.download_missing(manifest, entries, fetch=lambda url: real))

    assert outcomes["mcl-001"] == "downloaded"
    assert "does not match" in outcomes["mcl-002"]
    assert (tmp_path / "pdfs" / "paper.pdf").read_bytes() == real
    assert not (tmp_path / "pdfs" / "b.pdf").exists()
    assert dict(corpus.download_missing(manifest, entries[:1], fetch=lambda url: b""))["mcl-001"] == "already present"


def test_one_failed_download_does_not_stop_the_others(tmp_path: Path) -> None:
    first, second = make_pdf(["Paper one"]), make_pdf(["Paper two"])
    manifest = write_manifest(
        tmp_path,
        manifest_entry(first, download_url="https://example.org/gone.pdf"),
        manifest_entry(second, corpus_id="mcl-002", file="pdfs/two.pdf", doi=None, pmcid=None),
    )

    def fetch(url: str) -> bytes:
        if url.endswith("gone.pdf"):
            raise OSError("HTTP Error 404: Not Found")
        return second

    outcomes = dict(corpus.download_missing(manifest, load_manifest(manifest), fetch=fetch))

    assert outcomes["mcl-001"].startswith("download failed")
    assert outcomes["mcl-002"] == "downloaded"
