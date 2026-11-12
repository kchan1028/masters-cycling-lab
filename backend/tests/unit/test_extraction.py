import io
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from masters_cycling_lab.application.documents import safe_filename, upload_document
from masters_cycling_lab.config import Settings
from masters_cycling_lab.domain.extraction import ExtractedPage, normalize_text, remove_repeated_edge_lines
from masters_cycling_lab.infrastructure.db.session import make_engine
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage
from tests.helpers import make_pdf


def page(number: int, text: str) -> ExtractedPage:
    return ExtractedPage(page_number=number, label=None, text=text)


def test_normalize_text_cleans_whitespace_and_control_characters() -> None:
    raw = "Title  \r\nline\x00 two\x0c\n\n\n\nnext paragraph   \n"
    assert normalize_text(raw) == "Title\nline two\n\nnext paragraph"


def test_normalize_text_uses_composed_unicode() -> None:
    assert normalize_text("Cafe\u0301") == "Caf\u00e9"


def test_repeated_header_footer_and_page_numbers_are_removed_with_warnings() -> None:
    pages = [page(n, f"J Aging Phys Act 2021\nBody text of page {n}.\n{n}") for n in range(1, 6)]

    cleaned = remove_repeated_edge_lines(pages)

    assert [p.text for p in cleaned] == [f"Body text of page {n}." for n in range(1, 6)]
    assert any("header" in warning for warning in cleaned[0].warnings)
    assert any("footer" in warning for warning in cleaned[0].warnings)


def test_lines_that_repeat_on_too_few_pages_are_kept() -> None:
    headings = ["Methods", "Methods", "Results", "Discussion", "Limitations", "References"]
    bodies = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
    pages = [
        page(n, f"{heading}\n{body}") for n, (heading, body) in enumerate(zip(headings, bodies, strict=True), start=1)
    ]
    assert remove_repeated_edge_lines(pages) == pages


def test_short_documents_are_left_alone() -> None:
    pages = [page(n, "Same header\nText") for n in range(1, 4)]
    assert remove_repeated_edge_lines(pages) == pages


def test_only_edge_lines_are_candidates() -> None:
    pages = [page(n, f"Header\nRepeated middle line\nUnique {n}") for n in range(1, 6)]
    cleaned = remove_repeated_edge_lines(pages)
    assert all("Repeated middle line" in p.text for p in cleaned)


def test_upload_leaves_no_file_behind_when_the_database_fails(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://test@127.0.0.1:1/unused")
    storage = LocalFileStorage(tmp_path)

    with Session(make_engine(settings.database_url)) as session, pytest.raises(OperationalError):
        upload_document(session, storage, settings, "paper.pdf", io.BytesIO(make_pdf(["Some text."])), {})

    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_safe_filename_keeps_only_a_display_name() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\Users\\me\\paper.pdf") == "paper.pdf"
    assert safe_filename("bad\x00name.pdf") == "badname.pdf"
    assert safe_filename("") == "upload.pdf"
    assert safe_filename(None) == "upload.pdf"
    assert len(safe_filename("a" * 300 + ".pdf")) == 255
