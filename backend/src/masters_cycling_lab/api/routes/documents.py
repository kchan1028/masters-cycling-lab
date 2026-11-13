import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Path, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints

from masters_cycling_lab.api.dependencies import SessionDep, SettingsDep, StorageDep
from masters_cycling_lab.api.errors import ApiError
from masters_cycling_lab.api.routes.ingestion import JobOut
from masters_cycling_lab.application import documents
from masters_cycling_lab.application.documents import DocumentView

router = APIRouter(prefix="/documents", tags=["documents"])

AccessStatus = Literal["open_access", "user_provided", "restricted", "unknown"]
MetadataSource = Literal["user_supplied", "manifest_verified", "extracted_unverified"]
DOI_PATTERN = r"^10\.\d{4,9}/\S+$"
Author = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class DocumentOut(BaseModel):
    id: uuid.UUID
    original_filename: str
    title: str | None
    authors: list[str]
    publication_year: int | None
    doi: str | None
    source_url: str | None
    license: str | None
    access_status: AccessStatus
    # How far the bibliographic fields can be trusted. Titles read from PDF metadata are "extracted_unverified".
    metadata_source: MetadataSource
    byte_size: int
    sha256: str
    page_count: int | None
    # True once an index version is active. A reindex keeps the old one searchable until the new one is ready.
    searchable: bool
    active_index_version_id: uuid.UUID | None
    latest_job: JobOut | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view: DocumentView) -> "DocumentOut":
        document = view.document
        return cls(
            id=document.id,
            original_filename=document.original_filename,
            title=document.title,
            authors=document.authors,
            publication_year=document.publication_year,
            doi=document.doi,
            source_url=document.source_url,
            license=document.license,
            access_status=document.access_status,
            metadata_source=document.metadata_source,
            byte_size=document.byte_size,
            sha256=document.sha256,
            page_count=document.page_count,
            searchable=document.active_index_version_id is not None,
            active_index_version_id=document.active_index_version_id,
            latest_job=JobOut.model_validate(view.latest_job) if view.latest_job else None,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class UploadOut(BaseModel):
    document: DocumentOut
    # True when this exact file was already in the corpus. Nothing new was stored or queued.
    duplicate: bool


class MetadataPatch(BaseModel):
    """Corrections to bibliographic metadata. Send only the fields to change; null clears an optional field."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    authors: list[Author] = Field(default_factory=list, max_length=100)
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    doi: str | None = Field(default=None, pattern=DOI_PATTERN, max_length=200)
    source_url: AnyHttpUrl | None = None
    license: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    access_status: AccessStatus = "unknown"


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    index_version_id: uuid.UUID
    page_number: int  # physical page in the PDF, starting at 1
    page_label: str | None  # printed page label, when the PDF defines one
    text: str
    warnings: list[str]


DocumentId = Annotated[uuid.UUID, Path()]


@router.post(
    "",
    status_code=202,
    responses={200: {"model": UploadOut, "description": "This file is already in the corpus; nothing was queued."}},
)
def upload_document(
    response: Response,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="A PDF. Checked by content, not by file name.")],
    title: Annotated[str | None, Form(min_length=1, max_length=500)] = None,
    authors: Annotated[list[str] | None, Form(max_length=100)] = None,
    publication_year: Annotated[int | None, Form(ge=1800, le=2100)] = None,
    doi: Annotated[str | None, Form(pattern=DOI_PATTERN, max_length=200)] = None,
    source_url: Annotated[str | None, Form(pattern=r"^https?://\S+$", max_length=2000)] = None,
    license: Annotated[str | None, Form(min_length=1, max_length=200)] = None,
    access_status: Annotated[AccessStatus | None, Form()] = None,
) -> UploadOut:
    """Upload a PDF and queue it for ingestion (202). The same file again returns the existing document (200)."""
    supplied: dict[str, Any] = {
        "title": title,
        "authors": [author.strip() for author in authors or [] if author.strip()] or None,
        "publication_year": publication_year,
        "doi": doi,
        "source_url": source_url,
        "license": license,
        "access_status": access_status,
    }
    metadata = {field: value for field, value in supplied.items() if value is not None}
    view, duplicate = documents.upload_document(session, storage, settings, file.filename, file.file, metadata)
    if duplicate:
        response.status_code = 200
    return UploadOut(document=DocumentOut.from_view(view), duplicate=duplicate)


@router.get("")
def list_documents(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    views, total = documents.list_documents(session, limit, offset)
    return DocumentList(items=[DocumentOut.from_view(view) for view in views], total=total, limit=limit, offset=offset)


@router.get("/{document_id}")
def get_document(session: SessionDep, document_id: DocumentId) -> DocumentOut:
    return DocumentOut.from_view(documents.get_document(session, document_id))


@router.patch("/{document_id}")
def update_document(session: SessionDep, document_id: DocumentId, patch: MetadataPatch) -> DocumentOut:
    changes = patch.model_dump(exclude_unset=True)
    if "source_url" in changes and changes["source_url"] is not None:
        changes["source_url"] = str(changes["source_url"])
    return DocumentOut.from_view(documents.update_metadata(session, document_id, changes))


@router.delete("/{document_id}", status_code=204)
def delete_document(session: SessionDep, storage: StorageDep, document_id: DocumentId) -> Response:
    """Removes the document, its file, its indexes, and any answer history that quoted it. Cannot be undone."""
    documents.delete_document(session, storage, document_id)
    return Response(status_code=204)


@router.get(
    "/{document_id}/file",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}, "description": "The original PDF"}},
)
def get_document_file(session: SessionDep, storage: StorageDep, document_id: DocumentId) -> FileResponse:
    document = documents.get_document(session, document_id).document
    path = storage.path(document.storage_key)
    if not path.is_file():
        raise ApiError(500, "FILE_MISSING", "The stored PDF for this paper is missing.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.original_filename,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/{document_id}/pages/{page_number}")
def get_page(session: SessionDep, document_id: DocumentId, page_number: Annotated[int, Path(ge=1)]) -> PageOut:
    """Stored text of one physical page from the active index version, with extraction warnings."""
    return PageOut.model_validate(documents.get_page(session, document_id, page_number))


@router.post("/{document_id}/ingestions", status_code=202)
def reindex_document(session: SessionDep, settings: SettingsDep, document_id: DocumentId) -> JobOut:
    """Queue a rebuild of the document's index. The current index stays searchable until the new one is ready."""
    return JobOut.model_validate(documents.request_ingestion(session, settings, document_id))
