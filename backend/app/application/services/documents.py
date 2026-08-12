import asyncio
import errno
import hashlib
import logging
import os
import random
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.version import CONNECTOR_VERSION
from app.domain.ports.saas import DocumentDeliveryMetadata, PEKASaaSClient, SaaSClientError
from app.infrastructure.database.models.document import (
    DocumentDeliveryJobModel,
    DocumentModel,
)
from app.infrastructure.database.models.operations import AuditEventModel
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.security.secrets import SecretEncryptionService

logger = logging.getLogger(__name__)

MANAGED_DOCUMENT_SOURCE_ID = UUID("d0c0a001-6f05-4bd8-a123-000000000001")
MANAGED_DOCUMENT_SOURCE_TYPE = "filesystem_documents"
MANAGED_DOCUMENT_PATH = "/data/sources/documents"
MANAGED_INCLUDE_PATTERNS = [
    "**/*.txt",
    "**/*.md",
    "**/*.csv",
    "**/*.pdf",
    "**/*.docx",
    "**/*.xlsx",
]
MANAGED_EXCLUDE_PATTERNS = ["**/.*", "**/.DS_Store", "**/.peka-*", "**/~$*"]
TEMPORARY_PREFIX = ".peka-upload-"
SUPPORTED_MIME_TYPES: dict[str, set[str]] = {
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".csv": {"text/csv", "text/plain", "application/csv"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}


class DocumentError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class DocumentDeleteEligibility:
    can_delete: bool
    code: str | None = None
    reason: str | None = None
    status_code: int = 409
    deletion_in_progress: bool = False
    ownership_changed: bool = False


def _safe_relative_path(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\\", "/"))
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part.startswith(".") for part in path.parts)
    ):
        raise DocumentError("PATH_NOT_ALLOWED", "The document path is not allowed.")
    return path.as_posix()


def _safe_filename(value: str, maximum_length: int) -> str:
    filename = unicodedata.normalize("NFC", Path(value.replace("\\", "/")).name).strip()
    if (
        not filename
        or filename != value
        or len(filename) > maximum_length
        or filename.startswith(".")
        or filename in {".", ".."}
        or any(ord(character) < 32 for character in filename)
        or not re.fullmatch(r"[^/\\]+", filename)
    ):
        raise DocumentError("INVALID_FILENAME", "The uploaded filename is invalid.")
    return filename


def _inspect_file(path: Path, extension: str, supplied_mime: str | None) -> str:
    allowed = SUPPORTED_MIME_TYPES.get(extension)
    if allowed is None:
        raise DocumentError("UNSUPPORTED_FILE_TYPE", "This file type is not supported.")
    mime = (supplied_mime or "").split(";", 1)[0].strip().lower()
    if mime and mime not in allowed and mime != "application/octet-stream":
        raise DocumentError("UNSUPPORTED_FILE_TYPE", "The file type does not match its filename.")
    with path.open("rb") as stream:
        sample = stream.read(8192)
    if not sample:
        raise DocumentError("UNSUPPORTED_FILE_TYPE", "Empty files are not supported.")
    if extension == ".pdf":
        if not sample.startswith(b"%PDF-"):
            raise DocumentError(
                "UNSUPPORTED_FILE_TYPE", "The file type does not match its filename."
            )
        with path.open("rb") as stream:
            if b"/Encrypt" in stream.read(min(path.stat().st_size, 1024 * 1024)):
                raise DocumentError(
                    "UNSUPPORTED_FILE_TYPE", "Encrypted documents are not supported."
                )
        return "application/pdf"
    if extension in {".docx", ".xlsx"}:
        if not zipfile.is_zipfile(path):
            raise DocumentError(
                "UNSUPPORTED_FILE_TYPE", "The file type does not match its filename."
            )
        required = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
        try:
            with zipfile.ZipFile(path) as archive:
                if required not in archive.namelist() or any(
                    info.flag_bits & 0x1 for info in archive.infolist()
                ):
                    raise DocumentError(
                        "UNSUPPORTED_FILE_TYPE", "Encrypted or invalid documents are not supported."
                    )
        except zipfile.BadZipFile as exc:
            raise DocumentError(
                "UNSUPPORTED_FILE_TYPE", "The file type does not match its filename."
            ) from exc
        return next(iter(allowed))
    if b"\x00" in sample:
        raise DocumentError("UNSUPPORTED_FILE_TYPE", "The file type does not match its filename.")
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentError(
            "UNSUPPORTED_FILE_TYPE", "Text documents must use UTF-8 encoding."
        ) from exc
    return {".md": "text/markdown", ".csv": "text/csv"}.get(extension, "text/plain")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class ManagedDocumentService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._root = settings.managed_documents_root
        self._spool = settings.data_root / "spool" / "documents"
        self._operations = SqlAlchemyOperationsRepository(session)

    @property
    def max_files_per_request(self) -> int:
        return self._settings.document_max_files_per_request

    @staticmethod
    def _configuration(scan_interval_seconds: int) -> dict[str, object]:
        return {
            "path": MANAGED_DOCUMENT_PATH,
            "managed": True,
            "scan_interval_seconds": scan_interval_seconds,
            "include_patterns": MANAGED_INCLUDE_PATTERNS,
            "exclude_patterns": MANAGED_EXCLUDE_PATTERNS,
        }

    async def ensure_managed_source(self) -> SourceModel:
        await asyncio.to_thread(self._ensure_directories)
        sources = list((await self._session.scalars(select(SourceModel))).all())
        managed = [source for source in sources if source.system_managed]
        matching = [
            source
            for source in sources
            if source.plugin_type in {"filesystem_documents", "managed_documents"}
            and source.configuration.get("path") == MANAGED_DOCUMENT_PATH
        ]
        source = managed[0] if managed else matching[0] if matching else None
        now = datetime.now(UTC)
        initialized = source is None or not source.system_managed
        if source is None:
            source = SourceModel(
                id=MANAGED_DOCUMENT_SOURCE_ID,
                plugin_type=MANAGED_DOCUMENT_SOURCE_TYPE,
                name="Uploaded Documents",
                enabled=True,
                system_managed=True,
                configuration=self._configuration(300),
                health_status="healthy",
                last_success_at=now,
            )
            self._session.add(source)
        interval = int(source.configuration.get("scan_interval_seconds", 300))
        if not 30 <= interval <= 86400:
            interval = 300
        source.plugin_type = MANAGED_DOCUMENT_SOURCE_TYPE
        source.name = "Uploaded Documents"
        source.system_managed = True
        source.configuration = self._configuration(interval)
        for duplicate in managed[1:]:
            duplicate.system_managed = False
        await self._session.commit()
        await self._session.refresh(source)
        initialization_recorded = await self._session.scalar(
            select(AuditEventModel.id)
            .where(
                AuditEventModel.event_type == "document_source.initialized",
                AuditEventModel.target_id == str(source.id),
            )
            .limit(1)
        )
        if initialized or initialization_recorded is None:
            await self._operations.record_event(
                "document_source.initialized",
                "Managed document source initialized",
                target_type="source",
                target_id=str(source.id),
                component="documents",
            )
        return source

    async def source(self) -> SourceModel:
        source = await self._session.scalar(
            select(SourceModel).where(SourceModel.system_managed.is_(True)).limit(1)
        )
        return source if source else await self.ensure_managed_source()

    async def refresh_source(self) -> SourceModel:
        self._session.expire_all()
        return await self.source()

    async def update_source(self, enabled: bool, scan_interval_seconds: int) -> SourceModel:
        if not 30 <= scan_interval_seconds <= 86400:
            raise DocumentError(
                "INVALID_SCAN_INTERVAL",
                "Scan interval must be between 30 and 86400 seconds.",
            )
        source = await self.source()
        source.enabled = enabled
        source.configuration = self._configuration(scan_interval_seconds)
        source.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(source)
        return source

    async def test_source_health(self) -> SourceModel:
        source = await self.source()
        try:
            await asyncio.to_thread(self._ensure_directories)
            source.health_status = "healthy"
            source.last_error = None
            source.last_success_at = datetime.now(UTC)
        except DocumentError as exc:
            source.health_status = "unhealthy"
            source.last_error = str(exc)
            await self._session.commit()
            raise
        await self._session.commit()
        await self._session.refresh(source)
        return source

    async def mark_scan_failed(self, error: str) -> SourceModel:
        source = await self.source()
        source.health_status = "unhealthy"
        source.last_error = error[:2000]
        source.last_scan_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(source)
        return source

    def _ensure_directories(self) -> None:
        self._settings.ensure_managed_document_directory()
        self._spool.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._spool.chmod(0o700)
        for path in (self._root, self._spool):
            probe = path / f".peka-write-check-{uuid4()}"
            try:
                probe.touch(exist_ok=False)
            except OSError as exc:
                raise DocumentError(
                    "STORAGE_UNAVAILABLE", "Document storage is unavailable.", 503
                ) from exc
            finally:
                probe.unlink(missing_ok=True)

    async def list_page(
        self, page: int, page_size: int, *, show_deleted: bool = False
    ) -> tuple[list[DocumentModel], int]:
        source = await self.source()
        condition = DocumentModel.source_id == source.id
        if not show_deleted:
            condition = and_(
                condition,
                DocumentModel.deleted_at.is_(None),
                DocumentModel.deletion_requested.is_(False),
                DocumentModel.state.notin_(["deleted", "tombstoned", "missing"]),
                DocumentModel.local_status != "DELETED",
                DocumentModel.delivery_status != "DELETED",
            )
        total = int(
            await self._session.scalar(select(func.count(DocumentModel.id)).where(condition)) or 0
        )
        rows = await self._session.scalars(
            select(DocumentModel)
            .where(condition)
            .order_by(DocumentModel.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        documents = list(rows.all())
        await self.prepare_for_response(documents)
        return documents, total

    async def get(self, document_id: UUID) -> DocumentModel:
        source = await self.source()
        document = await self._session.get(DocumentModel, document_id)
        if document is None or document.source_id != source.id:
            raise DocumentError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        return document

    async def prepare_for_response(self, documents: list[DocumentModel]) -> list[DocumentModel]:
        if not documents:
            return documents
        source = await self.source()
        product = await self._operations.get_settings()
        registration_history_matches = await self._registration_history_matches(product)
        ownership_changed = False
        for document in documents:
            eligibility = self._delete_eligibility(
                document,
                source,
                product,
                registration_history_matches,
                backfill=True,
            )
            document.can_delete = eligibility.can_delete
            document.delete_unavailable_reason = eligibility.reason
            document.deletion_in_progress = eligibility.deletion_in_progress
            ownership_changed = ownership_changed or eligibility.ownership_changed
        if ownership_changed:
            await self._session.commit()
        return documents

    async def _registration_history_matches(self, product: object) -> bool:
        connector_id = getattr(product, "connector_id", None)
        tenant_id = getattr(product, "tenant_id", None)
        if not connector_id or not tenant_id:
            return False
        events = list(
            (
                await self._session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.event_type == "connector.registration_succeeded"
                    )
                )
            ).all()
        )
        return all(
            (not event.target_id or event.target_id == connector_id)
            and (not event.details.get("tenant_id") or str(event.details["tenant_id"]) == tenant_id)
            for event in events
        )

    def _delete_eligibility(
        self,
        document: DocumentModel,
        source: SourceModel,
        product: object,
        registration_history_matches: bool,
        *,
        backfill: bool,
    ) -> DocumentDeleteEligibility:
        if document.delivery_status == "DELETED":
            return DocumentDeleteEligibility(
                False,
                "DOCUMENT_ALREADY_DELETED",
                "This document has already been deleted.",
            )
        if document.deletion_requested or document.deleted_at:
            return DocumentDeleteEligibility(
                False,
                "DELETE_ALREADY_PENDING",
                "Document deletion is already in progress.",
                deletion_in_progress=True,
            )
        if document.state.casefold() in {"deleted", "tombstoned"}:
            return DocumentDeleteEligibility(
                False,
                "DOCUMENT_ALREADY_DELETED",
                "This document has already been deleted.",
            )
        if document.state.casefold() == "missing":
            return DocumentDeleteEligibility(
                False,
                "DOCUMENT_ALREADY_REMOVED",
                "The local document has already been removed.",
            )
        try:
            relative_path = _safe_relative_path(document.relative_path)
        except DocumentError:
            return DocumentDeleteEligibility(
                False,
                "INVALID_DOCUMENT_RECORD",
                "Document ownership cannot be safely established.",
                422,
            )
        target = self._root / relative_path
        try:
            resolved_parent = target.parent.resolve()
        except OSError:
            return DocumentDeleteEligibility(
                False,
                "INVALID_DOCUMENT_RECORD",
                "Document ownership cannot be safely established.",
                422,
            )
        if (
            document.source_id != source.id
            or self._root.resolve() not in (resolved_parent, *resolved_parent.parents)
            or target.is_symlink()
        ):
            return DocumentDeleteEligibility(
                False,
                "INVALID_DOCUMENT_OWNERSHIP",
                "Document ownership cannot be safely established.",
                422,
            )

        current_instance_id = str(getattr(product, "instance_id", "") or "")
        current_connector_id = str(getattr(product, "connector_id", "") or "")
        current_tenant_id = str(getattr(product, "tenant_id", "") or "")
        if document.owner_instance_id and document.owner_instance_id != current_instance_id:
            return DocumentDeleteEligibility(
                False,
                "DOCUMENT_CONNECTOR_MISMATCH",
                "This document belongs to another connector.",
                403,
            )
        if document.owner_connector_id and document.owner_connector_id != current_connector_id:
            return DocumentDeleteEligibility(
                False,
                "DOCUMENT_CONNECTOR_MISMATCH",
                "This document belongs to another connector.",
                403,
            )
        if document.owner_tenant_id and document.owner_tenant_id != current_tenant_id:
            return DocumentDeleteEligibility(
                False,
                "DOCUMENT_TENANT_MISMATCH",
                "This document belongs to another tenant.",
                403,
            )

        ownership_changed = False
        if not document.owner_instance_id and current_instance_id and backfill:
            document.owner_instance_id = current_instance_id
            ownership_changed = True
        missing_remote_ownership = not document.owner_connector_id or not document.owner_tenant_id
        if missing_remote_ownership:
            if (
                not current_connector_id
                or not current_tenant_id
                or not registration_history_matches
            ):
                return DocumentDeleteEligibility(
                    False,
                    "INVALID_DOCUMENT_OWNERSHIP",
                    "Document ownership cannot be safely established.",
                    422,
                    ownership_changed=ownership_changed,
                )
            if backfill:
                document.owner_connector_id = current_connector_id
                document.owner_tenant_id = current_tenant_id
                ownership_changed = True

        if not target.is_file():
            return DocumentDeleteEligibility(
                False,
                "DOCUMENT_ALREADY_REMOVED",
                "The local document has already been removed.",
                409,
                ownership_changed=ownership_changed,
            )
        return DocumentDeleteEligibility(True, ownership_changed=ownership_changed)

    async def upload(self, upload: UploadFile, batch_bytes: int) -> DocumentModel:
        source = await self.source()
        if not source.enabled:
            raise DocumentError(
                "SOURCE_DISABLED", "Enable the managed document source before uploading.", 409
            )
        filename = _safe_filename(
            upload.filename or "", self._settings.document_max_filename_length
        )
        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_MIME_TYPES:
            raise DocumentError("UNSUPPORTED_FILE_TYPE", "This file type is not supported.")
        if batch_bytes > self._settings.document_max_request_size_bytes:
            raise DocumentError(
                "BATCH_TOO_LARGE", "The upload request exceeds the maximum allowed size.", 413
            )
        temporary = self._root / f"{TEMPORARY_PREFIX}{uuid4()}.tmp"
        target = self._root / filename
        size = 0
        digest = hashlib.sha256()
        try:
            with temporary.open("xb") as output:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self._settings.document_max_file_size_bytes:
                        raise DocumentError(
                            "FILE_TOO_LARGE", "The file exceeds the maximum allowed size.", 413
                        )
                    if batch_bytes + size > self._settings.document_max_request_size_bytes:
                        raise DocumentError(
                            "BATCH_TOO_LARGE",
                            "The upload request exceeds the maximum allowed size.",
                            413,
                        )
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            mime = await asyncio.to_thread(_inspect_file, temporary, extension, upload.content_type)
            os.replace(temporary, target)
            directory_fd = os.open(self._root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            document = await self._upsert_stable(
                filename,
                target,
                digest.hexdigest(),
                mime,
                "UI_UPLOAD",
            )
            await self._operations.record_event(
                "document.ui_uploaded",
                f"Document {filename} was uploaded to the connector",
                target_type="document",
                target_id=str(document.id),
                details={"size_bytes": size},
                component="documents",
            )
            return document
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise DocumentError(
                    "INSUFFICIENT_SPACE", "There is not enough local storage for this file.", 507
                ) from exc
            raise DocumentError(
                "STORAGE_UNAVAILABLE", "Document storage is unavailable.", 503
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
            await upload.close()

    async def _upsert_stable(
        self, relative_path: str, path: Path, content_hash: str, mime: str, entry_method: str
    ) -> DocumentModel:
        source = await self.source()
        product = await self._operations.get_settings()
        relative_path = _safe_relative_path(relative_path)
        stat = await asyncio.to_thread(path.stat)
        now = datetime.now(UTC)
        document = await self._session.scalar(
            select(DocumentModel).where(
                DocumentModel.source_id == source.id,
                DocumentModel.relative_path == relative_path,
            )
        )
        changed = document is not None and (
            document.content_hash != content_hash or document.deletion_requested
        )
        if document is None:
            document = DocumentModel(
                source_id=source.id,
                relative_path=relative_path,
                filename=Path(relative_path).name,
                normalized_filename=Path(relative_path).name.casefold(),
                document_key=f"uploaded-documents/{relative_path}",
                extension=path.suffix.lower(),
                mime_type=mime,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                sha256=content_hash,
                content_hash=content_hash,
                discovered_at=now,
                first_seen_at=now,
                last_seen_at=now,
                local_status="READY",
                delivery_status="LOCAL_ONLY",
                knowledge_status="PENDING",
                state="active",
                stable_since_at=now,
                entry_method=entry_method,
                owner_instance_id=product.instance_id,
                owner_connector_id=product.connector_id,
                owner_tenant_id=product.tenant_id,
                created_at=now,
                updated_at=now,
            )
            self._session.add(document)
            await self._session.flush()
            event_type = "document.discovered"
        elif not changed:
            document.last_seen_at = now
            document.modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
            document.size_bytes = stat.st_size
            await self._session.commit()
            return document
        else:
            document.version_sequence += 1
            document.filename = Path(relative_path).name
            document.normalized_filename = document.filename.casefold()
            document.extension = path.suffix.lower()
            document.mime_type = mime
            document.size_bytes = stat.st_size
            document.modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
            document.sha256 = content_hash
            document.content_hash = content_hash
            document.last_seen_at = now
            document.stable_since_at = now
            document.local_status = "READY"
            document.delivery_status = "LOCAL_ONLY"
            document.knowledge_status = "PENDING"
            document.indexed_content_hash = None
            document.indexed_chunk_count = 0
            document.knowledge_error = None
            document.deletion_requested = False
            document.deleted_at = None
            document.state = "active"
            document.entry_method = entry_method
            document.updated_at = now
            event_type = "document.changed"
        await self._session.commit()
        await self._session.refresh(document)
        await self._operations.record_event(
            event_type,
            f"Document {document.filename} was {'changed' if changed else 'discovered'}",
            target_type="document",
            target_id=str(document.id),
            component="documents",
        )
        source.file_count = int(
            await self._session.scalar(
                select(func.count(DocumentModel.id)).where(
                    DocumentModel.source_id == source.id,
                    DocumentModel.deleted_at.is_(None),
                )
            )
            or 0
        )
        await self._session.commit()
        return document

    async def _queue(
        self, document: DocumentModel, operation: str, source_path: Path | None
    ) -> None:
        product = await self._operations.get_settings()
        identity = product.connector_id or product.instance_id or "unregistered"
        raw = (
            f"{identity}:{document.id}:{document.version_sequence}:"
            f"{document.content_hash}:{operation}"
        )
        key = hashlib.sha256(raw.encode()).hexdigest()
        spool_path: Path | None = None
        if operation == "UPSERT":
            spool_path = self._spool / f"{uuid4()}.bin"
            if source_path is None:
                raise DocumentError("STORAGE_UNAVAILABLE", "Document content is unavailable.", 503)
            await asyncio.to_thread(self._copy_spool, source_path, spool_path)
        existing = await self._session.scalar(
            select(DocumentDeliveryJobModel).where(
                DocumentDeliveryJobModel.document_id == document.id,
                DocumentDeliveryJobModel.version_sequence == document.version_sequence,
                DocumentDeliveryJobModel.operation == operation,
            )
        )
        if existing:
            if spool_path:
                spool_path.unlink(missing_ok=True)
            return
        job = DocumentDeliveryJobModel(
            document_id=document.id,
            content_hash=document.content_hash if operation == "UPSERT" else None,
            version_sequence=document.version_sequence,
            operation=operation,
            state="PENDING",
            attempts=0,
            next_retry_at=datetime.now(UTC),
            idempotency_key=key,
            spool_path=str(spool_path) if spool_path else None,
        )
        self._session.add(job)
        document.local_status = "QUEUED" if operation == "UPSERT" else "DELETED"
        document.delivery_status = "QUEUED" if operation == "UPSERT" else "PENDING_DELETE"
        await self._session.commit()
        await self._operations.record_event(
            "document.queued",
            f"Document {document.filename} was queued for PEKA delivery",
            target_type="document",
            target_id=str(document.id),
            details={"operation": operation, "correlation_id": str(job.correlation_id)},
            component="document_delivery",
        )

    @staticmethod
    def _copy_spool(source: Path, destination: Path) -> None:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())

    async def reconcile(self) -> dict[str, int]:
        source = await self.ensure_managed_source()
        if not source.enabled:
            raise DocumentError("SOURCE_DISABLED", "The managed document source is disabled.", 409)
        now = datetime.now(UTC)
        found: set[str] = set()
        counts = {"discovered": 0, "changed": 0, "unchanged": 0, "removed": 0, "delayed": 0}
        files = await asyncio.to_thread(self._walk_safe)
        for relative, path in files:
            found.add(relative)
            stat = path.stat()
            document = await self._session.scalar(
                select(DocumentModel).where(
                    DocumentModel.source_id == source.id,
                    DocumentModel.relative_path == relative,
                )
            )
            modified = datetime.fromtimestamp(stat.st_mtime, UTC)
            if document and document.deletion_requested:
                continue
            if document is None:
                document = DocumentModel(
                    source_id=source.id,
                    relative_path=relative,
                    filename=path.name,
                    normalized_filename=path.name.casefold(),
                    document_key=f"uploaded-documents/{relative}",
                    extension=path.suffix.lower(),
                    mime_type="application/octet-stream",
                    size_bytes=stat.st_size,
                    modified_at=modified,
                    sha256="",
                    content_hash="",
                    discovered_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    local_status="WAITING_FOR_STABILITY",
                    delivery_status="PENDING",
                    state="active",
                    stable_since_at=now,
                    entry_method="DIRECT_COPY",
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(document)
                await self._session.commit()
                counts["delayed"] += 1
                continue
            unchanged_stat = (
                document.size_bytes == stat.st_size and document.modified_at == modified
            )
            if not unchanged_stat:
                document.size_bytes = stat.st_size
                document.modified_at = modified
                document.stable_since_at = now
                document.local_status = "WAITING_FOR_STABILITY"
                document.last_seen_at = now
                await self._session.commit()
                counts["delayed"] += 1
                continue
            stable_since = document.stable_since_at or now
            if stable_since.tzinfo is None:
                stable_since = stable_since.replace(tzinfo=UTC)
            if now - stable_since < timedelta(seconds=self._settings.document_stability_seconds):
                counts["delayed"] += 1
                continue
            before = path.stat()
            try:
                mime = await asyncio.to_thread(_inspect_file, path, path.suffix.lower(), None)
                content_hash = await asyncio.to_thread(_hash_file, path)
            except DocumentError as exc:
                document.local_status = "UNSUPPORTED"
                document.delivery_status = "NOT_APPLICABLE"
                document.last_error_code = exc.code
                document.last_error_message = str(exc)
                await self._session.commit()
                continue
            after = path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                document.stable_since_at = now
                document.local_status = "WAITING_FOR_STABILITY"
                await self._session.commit()
                counts["delayed"] += 1
                continue
            old_hash = document.content_hash
            await self._upsert_stable(relative, path, content_hash, mime, "DIRECT_COPY")
            counts[
                "unchanged" if old_hash == content_hash else "changed" if old_hash else "discovered"
            ] += 1
        rows = list(
            (
                await self._session.scalars(
                    select(DocumentModel).where(
                        DocumentModel.source_id == source.id,
                        DocumentModel.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        for document in rows:
            if document.relative_path not in found:
                await self._request_delete(document, remove_file=False)
                counts["removed"] += 1
        source.last_scan_at = now
        source.last_success_at = now
        source.file_count = len(found)
        source.health_status = "healthy"
        source.last_error = None
        await self._session.commit()
        return counts

    async def reconcile_with_stability(self) -> dict[str, int]:
        first = await self.reconcile()
        if first["delayed"] == 0:
            return first
        await asyncio.sleep(self._settings.document_stability_seconds)
        second = await self.reconcile()
        return {
            "discovered": first["discovered"] + second["discovered"],
            "changed": first["changed"] + second["changed"],
            "unchanged": second["unchanged"],
            "removed": first["removed"] + second["removed"],
            "delayed": second["delayed"],
        }

    def _walk_safe(self) -> list[tuple[str, Path]]:
        root = self._root.resolve()
        results: list[tuple[str, Path]] = []
        for directory, names, filenames in os.walk(root, followlinks=False):
            names[:] = [
                name
                for name in names
                if not name.startswith(".") and not (Path(directory) / name).is_symlink()
            ]
            for filename in filenames:
                if filename.startswith(".") or filename.startswith(TEMPORARY_PREFIX):
                    continue
                path = Path(directory) / filename
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    relative = path.relative_to(root).as_posix()
                    _safe_relative_path(relative)
                except (ValueError, DocumentError):
                    continue
                results.append((relative, path))
        return results

    async def delete(self, document_id: UUID) -> None:
        document = await self.get(document_id)
        source = await self.source()
        product = await self._operations.get_settings()
        eligibility = self._delete_eligibility(
            document,
            source,
            product,
            await self._registration_history_matches(product),
            backfill=True,
        )
        if eligibility.ownership_changed:
            await self._session.commit()
        if not eligibility.can_delete:
            safe_document_id = str(document.id)[:8]
            safe_connector_id = str(product.connector_id or product.instance_id or "unknown")[:8]
            reason = eligibility.reason or "Document deletion was rejected."
            logger.warning(
                "Document deletion rejected: document=%s connector=%s status=%s reason=%s",
                safe_document_id,
                safe_connector_id,
                document.delivery_status,
                reason,
            )
            await self._operations.record_event(
                "document.deletion_rejected",
                f"Document deletion was rejected: {reason}",
                target_type="document",
                target_id=safe_document_id,
                details={
                    "connector_id": safe_connector_id,
                    "document_status": document.delivery_status,
                    "reason": eligibility.code,
                },
                level="WARNING",
                component="documents",
            )
            raise DocumentError(
                eligibility.code or "DOCUMENT_DELETE_REJECTED",
                reason,
                eligibility.status_code,
            )
        await self._request_delete(document, remove_file=True)

    async def _request_delete(self, document: DocumentModel, remove_file: bool) -> None:
        if document.deletion_requested:
            return
        if remove_file:
            target = self._root / document.relative_path
            resolved_parent = target.parent.resolve()
            if self._root.resolve() not in (resolved_parent, *resolved_parent.parents):
                raise DocumentError("PATH_NOT_ALLOWED", "The document path is not allowed.")
            target.unlink(missing_ok=True)
        document.version_sequence += 1
        document.deletion_requested = True
        document.deleted_at = datetime.now(UTC)
        document.local_status = "DELETED"
        document.delivery_status = "LOCAL_ONLY"
        document.knowledge_status = "DELETE_PENDING"
        document.state = "missing"
        await self._session.commit()
        source = await self.source()
        source.file_count = int(
            await self._session.scalar(
                select(func.count(DocumentModel.id)).where(
                    DocumentModel.source_id == source.id,
                    DocumentModel.deleted_at.is_(None),
                )
            )
            or 0
        )
        await self._session.commit()
        if not remove_file:
            await self._operations.record_event(
                "document.removed",
                f"Document {document.filename} was removed from the managed directory",
                target_type="document",
                target_id=str(document.id),
                component="documents",
            )
        await self._operations.record_event(
            "document.deletion_requested",
            f"Deletion was requested for document {document.filename}",
            target_type="document",
            target_id=str(document.id),
            component="documents",
        )

    async def retry(self, document_id: UUID) -> DocumentModel:
        document = await self.get(document_id)
        if document.knowledge_status != "FAILED":
            raise DocumentError(
                "INDEX_ALREADY_IN_PROGRESS", "No failed local indexing is available to retry.", 409
            )
        document.knowledge_status = "PENDING"
        document.knowledge_error = None
        document.local_status = "READY"
        await self._session.commit()
        await self._operations.record_event(
            "document.retry_requested",
            f"Local indexing retry was requested for document {document.filename}",
            target_type="document",
            target_id=str(document.id),
            component="local_knowledge",
        )
        return document


class DocumentDeliveryWorker:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        client: PEKASaaSClient,
        encryption: SecretEncryptionService,
    ) -> None:
        self._session = session
        self._settings = settings
        self._client = client
        self._encryption = encryption
        self._operations = SqlAlchemyOperationsRepository(session)

    async def recover_stale(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=15)
        jobs = list(
            (
                await self._session.scalars(
                    select(DocumentDeliveryJobModel).where(
                        DocumentDeliveryJobModel.state == "IN_PROGRESS",
                        DocumentDeliveryJobModel.started_at < cutoff,
                    )
                )
            ).all()
        )
        for job in jobs:
            job.state = "FAILED_RETRYABLE"
            job.next_retry_at = datetime.now(UTC)
            job.error_code = "STALE_JOB_RECOVERED"
            job.error_message = "Delivery was interrupted and has been queued again."
        await self._session.commit()
        return len(jobs)

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        job = await self._session.scalar(
            select(DocumentDeliveryJobModel)
            .where(
                DocumentDeliveryJobModel.state.in_(["PENDING", "FAILED_RETRYABLE"]),
                or_(
                    DocumentDeliveryJobModel.next_retry_at.is_(None),
                    DocumentDeliveryJobModel.next_retry_at <= now,
                ),
            )
            .order_by(DocumentDeliveryJobModel.created_at)
            .limit(1)
        )
        if job is None:
            return False
        job.state = "IN_PROGRESS"
        job.started_at = now
        job.attempts += 1
        document = await self._session.get(DocumentModel, job.document_id)
        if document is None:
            job.state = "CANCELLED"
            await self._session.commit()
            return True
        document.local_status = "UPLOADING" if job.operation == "UPSERT" else "DELETED"
        document.delivery_status = "UPLOADING"
        document.upload_attempt_count += 1
        document.last_upload_attempt_at = now
        await self._session.commit()
        await self._operations.record_event(
            "document.upload_started",
            f"PEKA delivery started for document {document.filename}",
            target_type="document",
            target_id=str(document.id),
            details={"operation": job.operation, "correlation_id": str(job.correlation_id)},
            component="document_delivery",
        )
        try:
            product = await self._operations.get_settings()
            if (
                not product.connector_id
                or not product.saas_url
                or not product.encrypted_connector_secret
            ):
                raise SaaSClientError(
                    "unavailable", "Register the connector before document delivery"
                )
            secret = self._encryption.decrypt(product.encrypted_connector_secret)
            metadata = DocumentDeliveryMetadata(
                source_id=document.source_id,
                document_key=document.document_key,
                relative_path=document.relative_path,
                filename=document.filename,
                mime_type=document.mime_type,
                size_bytes=document.size_bytes,
                content_hash=f"sha256:{job.content_hash}" if job.content_hash else None,
                modified_at=document.modified_at if job.operation == "UPSERT" else None,
                operation="upsert" if job.operation == "UPSERT" else "delete",
                connector_version=CONNECTOR_VERSION,
            )
            response = await self._client.deliver_document(
                product.saas_url,
                UUID(product.connector_id),
                secret,
                metadata,
                job.idempotency_key,
                Path(job.spool_path) if job.spool_path else None,
            )
            expected = f"sha256:{job.content_hash}" if job.content_hash else None
            if job.operation == "UPSERT" and response.content_hash != expected:
                raise SaaSClientError("hash_mismatch", "PEKA acknowledgement hash did not match")
            job.state = "SUCCEEDED"
            job.completed_at = datetime.now(UTC)
            job.error_code = None
            job.error_message = None
            if document.version_sequence == job.version_sequence:
                document.delivery_status = "DELETED" if job.operation == "DELETE" else "UPLOADED"
                document.local_status = "DELETED" if job.operation == "DELETE" else "UPLOADED"
                document.uploaded_at = job.completed_at
                document.remote_document_id = response.document_id
                document.remote_version_id = response.version_id
                document.last_error_code = None
                document.last_error_message = None
            await self._session.commit()
            if job.spool_path:
                await asyncio.to_thread(Path(job.spool_path).unlink, missing_ok=True)
            await self._operations.record_event(
                "document.deletion_acknowledged"
                if job.operation == "DELETE"
                else "document.upload_acknowledged",
                f"PEKA acknowledged {job.operation.lower()} for document {document.filename}",
                target_type="document",
                target_id=str(document.id),
                details={"correlation_id": str(job.correlation_id)},
                component="document_delivery",
            )
        except SaaSClientError as exc:
            permanent = exc.kind in {
                "authentication",
                "validation",
                "conflict",
                "hash_mismatch",
            }
            exhausted = job.attempts >= self._settings.document_job_max_attempts
            job.state = "FAILED_PERMANENT" if permanent or exhausted else "FAILED_RETRYABLE"
            job.error_code = {
                "authentication": "PEKA_AUTHENTICATION_FAILED",
                "validation": "PEKA_VALIDATION_REJECTED",
                "rate_limited": "PEKA_RATE_LIMITED",
            }.get(exc.kind, "PEKA_UNAVAILABLE" if not permanent else "UPLOAD_FAILED")
            job.error_message = str(exc)[:1000]
            job.next_retry_at = (
                None
                if permanent or exhausted
                else now
                + timedelta(
                    seconds=min(3600, 10 * (2 ** min(job.attempts - 1, 8))) + random.randint(0, 10)
                )
            )
            document.delivery_status = "FAILED"
            document.local_status = "UPLOAD_FAILED"
            document.last_error_code = job.error_code
            document.last_error_message = job.error_message
            await self._session.commit()
            await self._operations.record_event(
                "document.upload_failed",
                f"PEKA delivery failed for document {document.filename}",
                target_type="document",
                target_id=str(document.id),
                details={"error_code": job.error_code, "correlation_id": str(job.correlation_id)},
                level="ERROR",
                component="document_delivery",
            )
        return True

    async def counts(self) -> tuple[int, int]:
        pending = int(
            await self._session.scalar(
                select(func.count(DocumentDeliveryJobModel.id)).where(
                    DocumentDeliveryJobModel.state.in_(["PENDING", "FAILED_RETRYABLE"])
                )
            )
            or 0
        )
        stale = int(
            await self._session.scalar(
                select(func.count(DocumentDeliveryJobModel.id)).where(
                    and_(
                        DocumentDeliveryJobModel.state == "IN_PROGRESS",
                        DocumentDeliveryJobModel.started_at
                        < datetime.now(UTC) - timedelta(minutes=15),
                    )
                )
            )
            or 0
        )
        return pending, stale
