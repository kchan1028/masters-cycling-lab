from pathlib import Path

import pytest

from masters_cycling_lab.domain.extraction import IngestionProblem
from masters_cycling_lab.infrastructure.pdf.pymupdf_extractor import extract_pdf
from tests.helpers import make_pdf


def write(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "file.pdf"
    path.write_bytes(content)
    return path


def test_extracts_text_physical_pages_and_printed_labels(tmp_path: Path) -> None:
    pdf = make_pdf(["First page about recovery.", "Second page about strength."], title="A Study", roman_labels=True)

    extracted = extract_pdf(write(tmp_path, pdf), max_pages=10)

    assert [p.page_number for p in extracted.pages] == [1, 2]
    assert [p.label for p in extracted.pages] == ["i", "ii"]
    assert "recovery" in extracted.pages[0].text
    assert extracted.title == "A Study"
    assert extracted.extractor == "pymupdf"


def test_page_without_text_is_kept_empty_with_a_warning(tmp_path: Path) -> None:
    pdf = make_pdf(["Readable text.", ""], image_only_pages=(2,))

    extracted = extract_pdf(write(tmp_path, pdf), max_pages=10)

    assert extracted.pages[1].text == ""
    assert "OCR" in extracted.pages[1].warnings[0]


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (make_pdf(["secret"], password="pw"), "PDF_ENCRYPTED"),
        (make_pdf(["", ""], image_only_pages=(1, 2)), "OCR_REQUIRED"),
        (b"%PDF-1.7\nthis is not really a pdf", "PDF_CORRUPT"),
        (make_pdf(["a", "b", "c"]), "PDF_TOO_MANY_PAGES"),
    ],
)
def test_unusable_pdfs_fail_with_a_clear_code(tmp_path: Path, content: bytes, code: str) -> None:
    with pytest.raises(IngestionProblem) as problem:
        extract_pdf(write(tmp_path, content), max_pages=2)
    assert problem.value.code == code
    assert problem.value.message
