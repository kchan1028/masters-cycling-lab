from pathlib import Path

import pymupdf

from masters_cycling_lab.domain.extraction import ExtractedPage, ExtractedPdf, IngestionProblem, normalize_text

# PyMuPDF's default text flags, minus "preserve ligatures", so "ﬁ" comes out as "fi" and matches searches.
TEXT_FLAGS = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES


def extract_pdf(path: Path, max_pages: int) -> ExtractedPdf:
    """Plain text of every page, in the order the PDF stores it.

    Known limits: multi-column pages can come out with columns interleaved, tables lose their structure, and
    figures are skipped. Pages without a text layer are kept empty with a warning; OCR is out of scope.
    """
    try:
        document = pymupdf.open(path, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError) as exc:
        raise IngestionProblem("PDF_CORRUPT", "The file could not be opened as a PDF.") from exc

    with document:
        if document.needs_pass:
            raise IngestionProblem(
                "PDF_ENCRYPTED", "The PDF is password protected. Remove the password and upload it again."
            )
        if document.page_count == 0:
            raise IngestionProblem("PDF_EMPTY", "The PDF has no pages.")
        if document.page_count > max_pages:
            raise IngestionProblem(
                "PDF_TOO_MANY_PAGES",
                f"The PDF has {document.page_count} pages; the limit is {max_pages} (MAX_PDF_PAGES).",
            )
        try:
            pages = tuple(read_page(document.load_page(index)) for index in range(document.page_count))
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise IngestionProblem("PDF_CORRUPT", "The PDF is damaged and its pages could not be read.") from exc
        title = (document.metadata or {}).get("title", "").strip() or None

    if not any(page.text for page in pages):
        raise IngestionProblem(
            "OCR_REQUIRED",
            "No page has extractable text. The PDF is probably a scan, and OCR is not supported yet.",
        )
    return ExtractedPdf(pages=pages, title=title, extractor="pymupdf", extractor_version=pymupdf.VersionBind)


def read_page(page: pymupdf.Page) -> ExtractedPage:
    text = normalize_text(page.get_text("text", flags=TEXT_FLAGS))
    warnings: tuple[str, ...] = ()
    if not any(char.isalnum() for char in text):
        text = ""
        if page.get_images():
            warnings = ("No extractable text; the page looks scanned and would need OCR.",)
        else:
            warnings = ("No extractable text on this page.",)
    return ExtractedPage(page_number=page.number + 1, label=page.get_label() or None, text=text, warnings=warnings)


def first_pages_text(path: Path, pages: int = 2) -> str:
    """Raw text of the first few pages, for checking that a file is the paper it claims to be."""
    with pymupdf.open(path, filetype="pdf") as document:
        return " ".join(document.load_page(i).get_text() for i in range(min(pages, document.page_count)))
