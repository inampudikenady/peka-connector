import asyncio
import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.rate_limit import auth_rate_limiter
from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import DocumentModel
from app.infrastructure.database.models.operations import AuditEventModel
from app.infrastructure.database.models.source import SourceModel
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.database.session import engine, session_factory
from app.main import app

ADMIN_PASSWORD = "Strong!LocalPass123"
UNSET = object()


async def _reset_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    asyncio.run(_reset_database())
    auth_rate_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client


def _bootstrap(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "confirm_password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 201


def _login(
    client: TestClient, username: str = "admin", password: str = ADMIN_PASSWORD
) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _ooxml(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "<document />")
    return buffer.getvalue()


async def _register_local_connector() -> tuple[str, str]:
    connector_id = str(uuid4())
    tenant_id = str(uuid4())
    async with session_factory() as session:
        product = await SqlAlchemyOperationsRepository(session).get_settings()
        product.connector_id = connector_id
        product.tenant_id = tenant_id
        product.saas_url = "https://peka.example.test"
        product.encrypted_connector_secret = "encrypted-test-value"
        await session.commit()
    return connector_id, tenant_id


async def _change_document(
    document_id: str,
    *,
    entry_method: str | None = None,
    owner_instance_id: str | None | object = UNSET,
    owner_connector_id: str | None | object = UNSET,
    owner_tenant_id: str | None | object = UNSET,
    local_status: str | None = None,
    delivery_status: str | None = None,
) -> None:
    async with session_factory() as session:
        document = await session.get(DocumentModel, UUID(document_id))
        assert document
        if entry_method is not None:
            document.entry_method = entry_method
        if owner_instance_id is not UNSET:
            document.owner_instance_id = cast(str | None, owner_instance_id)
        if owner_connector_id is not UNSET:
            document.owner_connector_id = cast(str | None, owner_connector_id)
        if owner_tenant_id is not UNSET:
            document.owner_tenant_id = cast(str | None, owner_tenant_id)
        if local_status is not None:
            document.local_status = local_status
        if delivery_status is not None:
            document.delivery_status = delivery_status
        await session.commit()


async def _add_conflicting_registration_history() -> None:
    async with session_factory() as session:
        session.add(
            AuditEventModel(
                event_type="connector.registration_succeeded",
                target_id=str(uuid4()),
                target_type="connector",
                message="Historical connector registration succeeded",
                details={"tenant_id": str(uuid4())},
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


def test_supported_uploads_inventory_security_and_roles(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    files = [
        ("files", ("policy.txt", b"plain text", "text/plain")),
        ("files", ("readme.md", b"# Markdown", "text/markdown")),
        ("files", ("records.csv", b"name,value\nA,1\n", "text/csv")),
        ("files", ("brief.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
        (
            "files",
            (
                "letter.docx",
                _ooxml("word/document.xml"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
        (
            "files",
            (
                "workbook.xlsx",
                _ooxml("xl/workbook.xml"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ),
        ("files", ("malware.exe", b"MZ", "application/octet-stream")),
    ]
    response = client.post("/api/v1/documents/upload", headers=headers, files=files)
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [item["success"] for item in results] == [True] * 6 + [False]
    assert results[-1]["code"] == "UNSUPPORTED_FILE_TYPE"
    for name in (
        "policy.txt",
        "readme.md",
        "records.csv",
        "brief.pdf",
        "letter.docx",
        "workbook.xlsx",
    ):
        assert (get_settings().managed_documents_root / name).is_file()
    assert not any(
        path.name.startswith(".peka-upload-")
        for path in get_settings().managed_documents_root.iterdir()
    )

    inventory = client.get("/api/v1/documents", headers=headers)
    assert inventory.status_code == 200
    assert {item["filename"] for item in inventory.json()["items"]} >= {
        "policy.txt",
        "readme.md",
        "records.csv",
        "brief.pdf",
        "letter.docx",
        "workbook.xlsx",
    }
    source_list = client.get("/api/v1/sources", headers=headers).json()
    assert all(source["plugin_type"] != "managed_documents" for source in source_list)

    reader_password = "Viewer!StrongPass123"
    client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "document-reader",
            "password": reader_password,
            "confirm_password": reader_password,
            "role": "read_only",
        },
    )
    reader = _login(client, "document-reader", reader_password)
    assert client.get("/api/v1/documents", headers=reader).status_code == 200
    assert (
        client.post(
            "/api/v1/documents/upload",
            headers=reader,
            files={"files": ("forbidden.txt", b"no", "text/plain")},
        ).status_code
        == 403
    )
    document_id = inventory.json()["items"][0]["id"]
    assert client.post(f"/api/v1/documents/{document_id}/retry", headers=reader).status_code == 403
    assert client.delete(f"/api/v1/documents/{document_id}", headers=reader).status_code == 403


def test_all_supported_active_documents_can_be_deleted(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    asyncio.run(_register_local_connector())
    files = [
        ("files", ("delete.txt", b"plain text", "text/plain")),
        ("files", ("delete.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
        (
            "files",
            (
                "delete.docx",
                _ooxml("word/document.xml"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
        (
            "files",
            (
                "delete.xlsx",
                _ooxml("xl/workbook.xml"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ),
    ]
    upload = client.post("/api/v1/documents/upload", headers=headers, files=files)
    assert upload.status_code == 200
    documents = [item["document"] for item in upload.json()["results"]]
    assert all(document["can_delete"] for document in documents)
    for document in documents:
        deleted = client.delete(f"/api/v1/documents/{document['id']}", headers=headers)
        assert deleted.status_code == 204
        duplicate = client.delete(f"/api/v1/documents/{document['id']}", headers=headers)
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "DELETE_ALREADY_PENDING"

    active_only = client.get("/api/v1/documents", headers=headers).json()
    assert active_only["items"] == []
    assert active_only["total"] == 0
    with_deleted = client.get("/api/v1/documents?show_deleted=true", headers=headers).json()
    assert {item["id"] for item in with_deleted["items"]} == {
        document["id"] for document in documents
    }
    assert with_deleted["total"] == 4


def test_legacy_direct_copy_metadata_is_backfilled_and_deletable(
    client: TestClient,
) -> None:
    _bootstrap(client)
    headers = _login(client)
    asyncio.run(_register_local_connector())
    upload = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": ("legacy.xlsx", _ooxml("xl/workbook.xml"), "application/octet-stream")},
    )
    document_id = upload.json()["results"][0]["document"]["id"]
    asyncio.run(
        _change_document(
            document_id,
            entry_method="DIRECT_COPY",
            owner_instance_id=None,
            owner_connector_id=None,
            owner_tenant_id=None,
        )
    )

    listed = client.get("/api/v1/documents", headers=headers).json()["items"]
    legacy = next(document for document in listed if document["id"] == document_id)
    assert legacy["entry_method"] == "DIRECT_COPY"
    assert legacy["can_delete"] is True
    assert legacy["delete_unavailable_reason"] is None
    assert client.delete(f"/api/v1/documents/{document_id}", headers=headers).status_code == 204


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("owner_connector_id", "DOCUMENT_CONNECTOR_MISMATCH"),
        ("owner_tenant_id", "DOCUMENT_TENANT_MISMATCH"),
    ],
)
def test_cross_context_document_delete_is_rejected(
    client: TestClient, field: str, expected_code: str
) -> None:
    _bootstrap(client)
    headers = _login(client)
    asyncio.run(_register_local_connector())
    upload = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": (f"{field}.txt", b"owned elsewhere", "text/plain")},
    )
    document_id = upload.json()["results"][0]["document"]["id"]
    asyncio.run(_change_document(document_id, **{field: str(uuid4())}))

    listed = client.get("/api/v1/documents", headers=headers).json()["items"]
    document = next(item for item in listed if item["id"] == document_id)
    assert document["can_delete"] is False
    assert "another" in document["delete_unavailable_reason"]
    rejected = client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert rejected.status_code == 403
    assert rejected.json()["code"] == expected_code


def test_invalid_legacy_ownership_has_a_clear_reason(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    asyncio.run(_register_local_connector())
    upload = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": ("ambiguous.txt", b"ambiguous ownership", "text/plain")},
    )
    document_id = upload.json()["results"][0]["document"]["id"]
    asyncio.run(
        _change_document(
            document_id,
            owner_instance_id=None,
            owner_connector_id=None,
            owner_tenant_id=None,
        )
    )
    asyncio.run(_add_conflicting_registration_history())

    listed = client.get("/api/v1/documents", headers=headers).json()["items"]
    document = next(item for item in listed if item["id"] == document_id)
    assert document["can_delete"] is False
    assert document["delete_unavailable_reason"] == (
        "Document ownership cannot be safely established."
    )
    rejected = client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "INVALID_DOCUMENT_OWNERSHIP"


def test_processing_document_can_be_deleted_and_removed_file_cannot(
    client: TestClient,
) -> None:
    _bootstrap(client)
    headers = _login(client)
    asyncio.run(_register_local_connector())
    upload = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files=[
            ("files", ("processing.txt", b"processing", "text/plain")),
            ("files", ("removed.txt", b"removed", "text/plain")),
        ],
    ).json()["results"]
    processing_id = upload[0]["document"]["id"]
    removed_id = upload[1]["document"]["id"]
    asyncio.run(
        _change_document(
            processing_id,
            local_status="UPLOADING",
            delivery_status="UPLOADING",
        )
    )
    (get_settings().managed_documents_root / "removed.txt").unlink()

    listed = client.get("/api/v1/documents", headers=headers).json()["items"]
    by_id = {item["id"]: item for item in listed}
    assert by_id[processing_id]["can_delete"] is True
    assert by_id[removed_id]["can_delete"] is False
    assert "already been removed" in by_id[removed_id]["delete_unavailable_reason"]
    assert client.delete(f"/api/v1/documents/{processing_id}", headers=headers).status_code == 204
    removed = client.delete(f"/api/v1/documents/{removed_id}", headers=headers)
    assert removed.status_code == 409
    assert removed.json()["code"] == "DOCUMENT_ALREADY_REMOVED"


def test_filename_and_mime_validation_are_structured(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    mismatch = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": ("fake.pdf", b"not a pdf", "application/pdf")},
    )
    assert mismatch.status_code == 200
    assert mismatch.json()["results"][0]["code"] == "UNSUPPORTED_FILE_TYPE"
    hidden = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": (".DS_Store", b"metadata", "application/octet-stream")},
    )
    assert hidden.json()["results"][0]["code"] == "INVALID_FILENAME"
    traversal = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files={"files": ("../escape.txt", b"escape", "text/plain")},
    )
    assert traversal.json()["results"][0]["code"] == "INVALID_FILENAME"


async def _managed_source_count() -> int:
    async with session_factory() as session:
        return int(
            await session.scalar(
                select(func.count(SourceModel.id)).where(SourceModel.system_managed.is_(True))
            )
            or 0
        )


def test_managed_source_is_singular_fixed_and_protected(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    first = client.get("/api/v1/documents/source", headers=headers)
    assert first.status_code == 200
    source = first.json()
    assert source["name"] == "Uploaded Documents"
    assert source["plugin_type"] == "filesystem_documents"
    assert source["path"] == "/data/sources/documents"
    assert source["enabled"] is True
    assert source["system_managed"] is True
    assert source["scan_interval_seconds"] == 300
    assert asyncio.run(_managed_source_count()) == 1
    assert client.get("/api/v1/documents/source", headers=headers).json()["id"] == source["id"]
    assert asyncio.run(_managed_source_count()) == 1

    path_edit = client.put(
        "/api/v1/documents/source",
        headers=headers,
        json={
            "enabled": True,
            "scan_interval_seconds": 300,
            "path": "/tmp/escape",
        },
    )
    assert path_edit.status_code == 422
    assert client.delete(f"/api/v1/sources/{source['id']}", headers=headers).status_code == 404
    assert (
        client.put(
            f"/api/v1/sources/{source['id']}",
            headers=headers,
            json={"name": "Changed", "enabled": False, "configuration": {}},
        ).status_code
        == 404
    )


def test_managed_source_settings_scan_and_role_enforcement(client: TestClient) -> None:
    _bootstrap(client)
    headers = _login(client)
    disabled = client.put(
        "/api/v1/documents/source",
        headers=headers,
        json={"enabled": False, "scan_interval_seconds": 600},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["scan_interval_seconds"] == 600
    assert disabled.json()["next_scheduled_scan_at"] is None
    invalid = client.put(
        "/api/v1/documents/source",
        headers=headers,
        json={"enabled": True, "scan_interval_seconds": 10},
    )
    assert invalid.status_code == 422
    enabled = client.put(
        "/api/v1/documents/source",
        headers=headers,
        json={"enabled": True, "scan_interval_seconds": 600},
    )
    assert enabled.status_code == 200
    assert enabled.json()["next_scheduled_scan_at"] is not None
    assert client.post("/api/v1/documents/source/test", headers=headers).status_code == 200
    assert client.post("/api/v1/documents/source/scan", headers=headers).status_code == 200

    reader_password = "Viewer!StrongPass123"
    client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "source-reader",
            "password": reader_password,
            "confirm_password": reader_password,
            "role": "read_only",
        },
    )
    reader = _login(client, "source-reader", reader_password)
    assert client.get("/api/v1/documents/source", headers=reader).status_code == 200
    assert (
        client.put(
            "/api/v1/documents/source",
            headers=reader,
            json={"enabled": False, "scan_interval_seconds": 300},
        ).status_code
        == 403
    )
    assert client.post("/api/v1/documents/source/scan", headers=reader).status_code == 403
    assert client.post("/api/v1/documents/source/test", headers=reader).status_code == 403
