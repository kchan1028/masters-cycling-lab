from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from masters_cycling_lab.application import corpus
from masters_cycling_lab.application.corpus import load_manifest
from masters_cycling_lab.infrastructure.db.models import IngestionJob
from tests.helpers import make_pdf, manifest_entry, write_manifest
from tests.integration.lab import Lab


def test_ingest_uses_manifest_metadata_and_is_idempotent(lab: Lab, tmp_path: Path) -> None:
    pdf = make_pdf(["Recovery in Masters Cyclists\nBody text about recovery."])
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "paper.pdf").write_bytes(pdf)
    manifest = write_manifest(tmp_path, manifest_entry(pdf))
    entries = load_manifest(manifest)

    with Session(lab.engine) as session:
        [(_, view, duplicate)] = corpus.ingest(session, lab.storage, lab.settings, manifest, entries)
        document = view.document
        assert not duplicate
        assert (document.title, document.publication_year, document.doi) == (
            "Recovery in Masters Cyclists",
            2020,
            "10.1234/test.1",
        )
        assert (document.metadata_source, document.access_status) == ("manifest_verified", "open_access")
        assert corpus.index_status(session, entries) == {"mcl-001": "uploaded, not searchable yet"}

    lab.ingest_next()

    with Session(lab.engine) as session:
        [(_, again, duplicate)] = corpus.ingest(session, lab.storage, lab.settings, manifest, entries)
        assert duplicate and again.document.id == document.id
        assert session.scalar(select(func.count()).select_from(IngestionJob)) == 1
        assert corpus.index_status(session, entries) == {"mcl-001": "searchable"}
