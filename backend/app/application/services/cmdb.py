import csv
import hashlib
import io
import re
import unicodedata
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
from xml.etree import ElementTree

from fastapi import UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.inventory import (
    CMDB_FIELDS,
    InventoryService,
    normalize_cmdb_row,
    row_checksum,
)
from app.core.config import Settings
from app.infrastructure.database.models.inventory import (
    CMDBDatasetModel,
    CMDBDatasetVersionModel,
    CMDBMappingProfileModel,
    CMDBRecordModel,
)

OOXML_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
CELL_REF = re.compile(r"([A-Z]+)\d+")


class CMDBError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _column_index(reference: str) -> int:
    match = CELL_REF.match(reference)
    if not match:
        return 0
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - 64
    return value - 1


def _xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    info = archive.getinfo(name)
    if info.file_size > 50 * 1024 * 1024 or info.compress_size == 0 and info.file_size:
        raise CMDBError("UNSAFE_WORKBOOK", "Workbook XML is too large or malformed.")
    if info.file_size > max(1, info.compress_size) * 200:
        raise CMDBError("UNSAFE_WORKBOOK", "Workbook compression ratio is unsafe.")
    try:
        return ElementTree.fromstring(archive.read(name))
    except (ElementTree.ParseError, KeyError, RuntimeError) as exc:
        raise CMDBError("MALFORMED_WORKBOOK", "The workbook cannot be parsed safely.") from exc


class SafeWorkbook:
    def __init__(self, path: Path) -> None:
        try:
            self.archive = zipfile.ZipFile(path)
            names = set(self.archive.namelist())
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise CMDBError(
                    "UNSUPPORTED_WORKBOOK", "The file is not a supported XLSX workbook."
                )
            if any(
                name.lower().endswith(("vbaproject.bin", ".exe", ".dll"))
                or name.startswith("/")
                or ".." in Path(name).parts
                for name in names
            ):
                raise CMDBError("UNSAFE_WORKBOOK", "The workbook contains unsupported content.")
            if sum(item.file_size for item in self.archive.infolist()) > 200 * 1024 * 1024:
                raise CMDBError("UNSAFE_WORKBOOK", "The expanded workbook is too large.")
            self.shared_strings = self._shared_strings(names)
            self.sheets = self._sheet_paths()
        except (zipfile.BadZipFile, KeyError) as exc:
            raise CMDBError("MALFORMED_WORKBOOK", "The workbook is malformed.") from exc

    def close(self) -> None:
        self.archive.close()

    def _shared_strings(self, names: set[str]) -> list[str]:
        if "xl/sharedStrings.xml" not in names:
            return []
        root = _xml(self.archive, "xl/sharedStrings.xml")
        return [
            "".join(node.text or "" for node in item.findall(".//x:t", OOXML_NS))
            for item in root.findall("x:si", OOXML_NS)
        ]

    def _sheet_paths(self) -> dict[str, str]:
        workbook = _xml(self.archive, "xl/workbook.xml")
        relationships = _xml(self.archive, "xl/_rels/workbook.xml.rels")
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in relationships.findall("r:Relationship", REL_NS)
            if item.attrib.get("TargetMode") != "External"
        }
        sheets: dict[str, str] = {}
        for sheet in workbook.findall("x:sheets/x:sheet", OOXML_NS):
            rel_id = sheet.attrib.get(DOC_REL)
            target = targets.get(rel_id or "")
            if target:
                clean = target.lstrip("/")
                sheets[sheet.attrib["name"]] = clean if clean.startswith("xl/") else f"xl/{clean}"
        if not sheets:
            raise CMDBError("MALFORMED_WORKBOOK", "The workbook has no readable worksheets.")
        return sheets

    def rows(self, sheet_name: str) -> list[list[str]]:
        target = self.sheets.get(sheet_name)
        if not target:
            raise CMDBError("SHEET_NOT_FOUND", "The selected worksheet does not exist.")
        root = _xml(self.archive, target)
        result: list[list[str]] = []
        for row in root.findall(".//x:sheetData/x:row", OOXML_NS):
            values: list[str] = []
            for cell in row.findall("x:c", OOXML_NS):
                index = _column_index(cell.attrib.get("r", "A1"))
                while len(values) <= index:
                    values.append("")
                kind = cell.attrib.get("t")
                value_node = cell.find("x:v", OOXML_NS)
                if kind == "inlineStr":
                    value = "".join(
                        item.text or "" for item in cell.findall(".//x:is/x:t", OOXML_NS)
                    )
                elif value_node is None:
                    value = ""
                elif kind == "s":
                    try:
                        value = self.shared_strings[int(value_node.text or "0")]
                    except (ValueError, IndexError):
                        value = ""
                elif kind == "b":
                    value = "TRUE" if value_node.text == "1" else "FALSE"
                else:
                    value = value_node.text or ""
                values[index] = value
            result.append(values)
        return result


def _unique_headers(row: list[str]) -> list[str]:
    headers: list[str] = []
    counts: dict[str, int] = {}
    for index, item in enumerate(row, 1):
        base = str(item).strip() or f"Column {index}"
        counts[base] = counts.get(base, 0) + 1
        headers.append(base if counts[base] == 1 else f"{base} ({counts[base]})")
    return headers


class CMDBService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def upload(
        self,
        upload: UploadFile,
        dataset_name: str,
        dataset_id: UUID | None,
    ) -> dict[str, object]:
        filename = unicodedata.normalize("NFC", upload.filename or "").strip()
        if (
            not filename
            or filename != Path(filename.replace("\\", "/")).name
            or filename.startswith(".")
            or any(ord(character) < 32 for character in filename)
        ):
            raise CMDBError("INVALID_FILENAME", "The uploaded filename is invalid.")
        extension = Path(filename).suffix.casefold()
        if extension not in {".csv", ".xlsx"}:
            raise CMDBError("UNSUPPORTED_FILE_TYPE", "Only CSV and XLSX files are supported.")
        mime = (upload.content_type or "").split(";", 1)[0].casefold()
        expected = {
            ".csv": {"text/csv", "text/plain", "application/csv", "application/octet-stream"},
            ".xlsx": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/octet-stream",
            },
        }
        if mime and mime not in expected[extension]:
            raise CMDBError(
                "UNSUPPORTED_FILE_TYPE", "The file MIME type does not match its extension."
            )
        root = self.settings.managed_cmdb_root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        generated = f"{uuid4().hex}{extension}"
        destination = (root / generated).resolve()
        if destination.parent != root.resolve():
            raise CMDBError("PATH_NOT_ALLOWED", "The storage path is not allowed.")
        digest = hashlib.sha256()
        size = 0
        try:
            with destination.open("xb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.cmdb_max_file_size_bytes:
                        raise CMDBError(
                            "FILE_TOO_LARGE",
                            "The CMDB file exceeds the configured size limit.",
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        )
                    digest.update(chunk)
                    handle.write(chunk)
            if extension == ".xlsx":
                workbook = SafeWorkbook(destination)
                sheets = list(workbook.sheets)
                workbook.close()
            else:
                self._csv_rows(destination, limit=2)
                sheets = []
            dataset = await self._dataset(dataset_id, dataset_name)
            version_number = (
                int(
                    await self.session.scalar(
                        select(func.max(CMDBDatasetVersionModel.version_number)).where(
                            CMDBDatasetVersionModel.dataset_id == dataset.id
                        )
                    )
                    or 0
                )
                + 1
            )
            version = CMDBDatasetVersionModel(
                dataset_id=dataset.id,
                version_number=version_number,
                original_filename=filename,
                stored_filename=generated,
                stored_path=f"/data/sources/cmdb/{generated}",
                checksum=digest.hexdigest(),
                file_type=extension[1:],
                file_size=size,
            )
            self.session.add(version)
            await self.session.flush()
            preview = await self.preview(version.id, sheets[0] if sheets else None, 1)
            await self.session.commit()
            await self.session.refresh(version)
            return {
                "dataset_id": dataset.id,
                "version_id": version.id,
                "version_number": version.version_number,
                "filename": filename,
                "file_type": extension[1:],
                "file_size": size,
                "checksum": version.checksum,
                "sheets": sheets,
                **preview,
            }
        except Exception:
            await self.session.rollback()
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    async def _dataset(self, dataset_id: UUID | None, name: str) -> CMDBDatasetModel:
        clean_name = name.strip()
        if not clean_name:
            raise CMDBError("INVALID_DATASET_NAME", "Dataset name is required.")
        if dataset_id:
            dataset = await self.session.get(CMDBDatasetModel, dataset_id)
            if not dataset or dataset.deleted_at:
                raise CMDBError("DATASET_NOT_FOUND", "The dataset was not found.", 404)
            return dataset
        dataset = CMDBDatasetModel(name=clean_name)
        self.session.add(dataset)
        await self.session.flush()
        return dataset

    def _csv_rows(self, path: Path, limit: int | None = None) -> list[list[str]]:
        try:
            data = path.read_bytes()
            text = data.decode("utf-8-sig")
        except (UnicodeDecodeError, OSError) as exc:
            raise CMDBError("MALFORMED_CSV", "CSV files must use UTF-8 encoding.") from exc
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows: list[list[str]] = []
        try:
            for row in csv.reader(io.StringIO(text), dialect):
                rows.append(row)
                if limit and len(rows) >= limit:
                    break
        except csv.Error as exc:
            raise CMDBError("MALFORMED_CSV", "The CSV file is malformed.") from exc
        return rows

    def _rows(self, version: CMDBDatasetVersionModel, sheet_name: str | None) -> list[list[str]]:
        path = self.settings.managed_cmdb_root / version.stored_filename
        if version.file_type == "csv":
            return self._csv_rows(path)
        workbook = SafeWorkbook(path)
        try:
            selected = sheet_name or next(iter(workbook.sheets))
            return workbook.rows(selected)
        finally:
            workbook.close()

    async def preview(
        self, version_id: UUID, sheet_name: str | None, header_row: int
    ) -> dict[str, object]:
        version = await self._version(version_id)
        rows = self._rows(version, sheet_name)
        if not 1 <= header_row <= max(1, len(rows)):
            raise CMDBError("INVALID_HEADER_ROW", "The selected header row is out of range.")
        headers = _unique_headers(rows[header_row - 1] if rows else [])
        preview = [
            {
                header: (row[index] if index < len(row) else "")
                for index, header in enumerate(headers)
            }
            for row in rows[header_row : header_row + 20]
            if any(str(item).strip() for item in row)
        ]
        suggested: dict[str, str] = {}
        aliases = {
            "ip": "primary_ip",
            "ip address": "primary_ip",
            "os": "operating_system",
            "owner": "business_owner",
            "instance id": "cloud_instance_id",
            "host": "hostname",
            "host name": "hostname",
        }
        for header in headers:
            key = re.sub(r"[_-]+", " ", header.casefold()).strip()
            field = aliases.get(key, key.replace(" ", "_"))
            if field in CMDB_FIELDS and field not in suggested.values():
                suggested[header] = field
        return {
            "sheet_name": sheet_name,
            "header_row": header_row,
            "headers": headers,
            "preview_rows": preview,
            "suggested_mapping": suggested,
            "detected_total_rows": max(0, len(rows) - header_row),
        }

    async def import_version(
        self,
        version_id: UUID,
        sheet_name: str | None,
        header_row: int,
        mapping: dict[str, str],
        profile_id: UUID | None = None,
    ) -> dict[str, object]:
        version = await self._version(version_id)
        if version.status == "imported":
            raise CMDBError("ALREADY_IMPORTED", "This dataset version is already imported.", 409)
        targets = [field for field in mapping.values() if field and field != "ignored"]
        if len(targets) != len(set(targets)):
            raise CMDBError("DUPLICATE_MAPPING", "A PEKA field may only be mapped once.")
        if any(field not in CMDB_FIELDS for field in targets):
            raise CMDBError("INVALID_MAPPING", "The mapping contains an unsupported PEKA field.")
        rows = self._rows(version, sheet_name)
        if not 1 <= header_row <= len(rows):
            raise CMDBError("INVALID_HEADER_ROW", "The selected header row is out of range.")
        headers = _unique_headers(rows[header_row - 1])
        active_mapping = {source: field for source, field in mapping.items() if field != "ignored"}
        if not active_mapping or any(source not in headers for source in active_mapping):
            raise CMDBError(
                "INVALID_MAPPING", "The mapping does not match the selected header row."
            )
        raw_rows: list[tuple[int, dict[str, object]]] = []
        for source_row, values in enumerate(rows[header_row:], header_row + 1):
            raw: dict[str, object] = {
                header: values[index] if index < len(values) else ""
                for index, header in enumerate(headers)
            }
            if any(str(value).strip() for value in raw.values()):
                raw_rows.append((source_row, raw))
        if len(raw_rows) > self.settings.cmdb_max_row_count:
            raise CMDBError(
                "TOO_MANY_ROWS",
                "The CMDB file exceeds the configured row-count limit.",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        normalized_rows: list[tuple[int, dict[str, object], dict[str, object], list[str], str]] = []
        key_counts: dict[str, int] = {}
        checksum_counts: dict[str, int] = {}
        for source_row, raw in raw_rows:
            normalized, errors = normalize_cmdb_row(raw, active_mapping)
            checksum = row_checksum(normalized)
            key = str(normalized.get("source_record_key") or "").strip()
            if key:
                key_counts[key] = key_counts.get(key, 0) + 1
            checksum_counts[checksum] = checksum_counts.get(checksum, 0) + 1
            normalized_rows.append((source_row, raw, normalized, errors, checksum))
        valid = invalid = duplicates = 0
        records: list[CMDBRecordModel] = []
        for source_row, raw, normalized, errors, checksum in normalized_rows:
            key = str(normalized.get("source_record_key") or "").strip()
            if key and key_counts[key] > 1:
                errors.append("duplicate source_record_key")
            if checksum_counts[checksum] > 1:
                errors.append("duplicate normalized row")
                duplicates += 1
            validation_status = "invalid" if errors else "valid"
            valid += validation_status == "valid"
            invalid += validation_status == "invalid"
            record = CMDBRecordModel(
                dataset_version_id=version.id,
                source_row_number=source_row,
                source_record_key=key or None,
                hostname=normalized.get("hostname_normalized"),
                fqdn=normalized.get("fqdn_normalized"),
                primary_ip=normalized.get("primary_ip_normalized"),
                cloud_instance_id=normalized.get("cloud_instance_id"),
                serial_number=normalized.get("serial_number"),
                asset_tag=normalized.get("asset_tag"),
                normalized_fields_json=normalized,
                raw_fields_json=raw,
                validation_status=validation_status,
                validation_errors_json=errors,
                row_checksum=checksum,
            )
            records.append(record)
            self.session.add(record)
        version.sheet_name = sheet_name
        version.header_row = header_row
        version.mapping_json = active_mapping
        version.mapping_profile_id = profile_id
        version.total_rows = len(records)
        version.valid_rows = valid
        version.invalid_rows = invalid
        version.duplicate_rows = duplicates
        version.status = "imported"
        version.imported_at = datetime.now(UTC)
        dataset = await self.session.get(CMDBDatasetModel, version.dataset_id)
        if not dataset:
            raise CMDBError("DATASET_NOT_FOUND", "The dataset was not found.", 404)
        previous_id = dataset.current_version_id
        dataset.current_version_id = version.id
        dataset.status = "active"
        dataset.updated_at = datetime.now(UTC)
        if previous_id:
            previous = await self.session.get(CMDBDatasetVersionModel, previous_id)
            if previous:
                previous.status = "superseded"
        await self.session.flush()
        inventory = InventoryService(self.session)
        ambiguous_matches = 0
        for record in records:
            if record.validation_status == "valid":
                observation = await inventory.ingest_cmdb_record(record)
                ambiguous_matches += observation.status == "ambiguous"
        await inventory.reconcile_cmdb_relationships()
        await self.session.commit()
        return {
            "dataset_id": dataset.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "total_rows": len(records),
            "valid_rows": valid,
            "invalid_rows": invalid,
            "duplicate_rows": duplicates,
            "ambiguous_matches": ambiguous_matches,
            "previous_version_id": previous_id,
            "status": "imported",
        }

    async def save_profile(
        self,
        name: str,
        mapping: dict[str, str],
        normalization: dict[str, object],
    ) -> CMDBMappingProfileModel:
        if len([value for value in mapping.values() if value != "ignored"]) != len(
            set(value for value in mapping.values() if value != "ignored")
        ):
            raise CMDBError("DUPLICATE_MAPPING", "A PEKA field may only be mapped once.")
        profile = CMDBMappingProfileModel(
            name=name.strip(),
            mapping_json=mapping,
            normalization_json=normalization,
        )
        self.session.add(profile)
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def list_profiles(self) -> list[CMDBMappingProfileModel]:
        return list(
            (
                await self.session.scalars(
                    select(CMDBMappingProfileModel).order_by(CMDBMappingProfileModel.name)
                )
            ).all()
        )

    async def list_datasets(self) -> list[dict[str, object]]:
        datasets = list(
            (
                await self.session.scalars(
                    select(CMDBDatasetModel)
                    .where(CMDBDatasetModel.deleted_at.is_(None))
                    .order_by(CMDBDatasetModel.updated_at.desc())
                )
            ).all()
        )
        results: list[dict[str, object]] = []
        for item in datasets:
            version = (
                await self.session.get(CMDBDatasetVersionModel, item.current_version_id)
                if item.current_version_id
                else await self.session.scalar(
                    select(CMDBDatasetVersionModel)
                    .where(CMDBDatasetVersionModel.dataset_id == item.id)
                    .order_by(CMDBDatasetVersionModel.version_number.desc())
                    .limit(1)
                )
            )
            results.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "status": item.status,
                    "current_version_id": item.current_version_id,
                    "current_version": version.version_number if version else None,
                    "source_filename": version.original_filename if version else None,
                    "imported_at": version.imported_at if version else None,
                    "total_rows": version.total_rows if version else 0,
                    "valid_rows": version.valid_rows if version else 0,
                    "invalid_rows": version.invalid_rows if version else 0,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                }
            )
        return results

    async def list_records(
        self,
        page: int,
        page_size: int,
        search: str | None,
        validation_status: str | None,
        dataset_id: UUID | None,
    ) -> tuple[list[dict[str, object]], int]:
        filters = []
        if validation_status:
            filters.append(CMDBRecordModel.validation_status == validation_status)
        if dataset_id:
            dataset_version_query = select(CMDBDatasetVersionModel.id).where(
                CMDBDatasetVersionModel.dataset_id == dataset_id
            )
            filters.append(CMDBRecordModel.dataset_version_id.in_(dataset_version_query))
        if search:
            escaped = search.replace("%", "\\%").replace("_", "\\_")
            filters.append(
                or_(
                    CMDBRecordModel.hostname.ilike(f"%{escaped}%", escape="\\"),
                    CMDBRecordModel.fqdn.ilike(f"%{escaped}%", escape="\\"),
                    CMDBRecordModel.primary_ip.ilike(f"%{escaped}%", escape="\\"),
                    CMDBRecordModel.source_record_key.ilike(f"%{escaped}%", escape="\\"),
                )
            )
        total = int(
            await self.session.scalar(select(func.count(CMDBRecordModel.id)).where(*filters)) or 0
        )
        records = list(
            (
                await self.session.scalars(
                    select(CMDBRecordModel)
                    .where(*filters)
                    .order_by(CMDBRecordModel.created_at.desc(), CMDBRecordModel.source_row_number)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        version_ids = {item.dataset_version_id for item in records}
        versions = (
            {
                item.id: item
                for item in (
                    await self.session.scalars(
                        select(CMDBDatasetVersionModel).where(
                            CMDBDatasetVersionModel.id.in_(version_ids)
                        )
                    )
                ).all()
            }
            if version_ids
            else {}
        )
        return [
            {
                "id": item.id,
                "dataset_version_id": item.dataset_version_id,
                "dataset_version": versions[item.dataset_version_id].version_number,
                "source_row_number": item.source_row_number,
                "normalized_fields": item.normalized_fields_json,
                "validation_status": item.validation_status,
                "validation_errors": item.validation_errors_json,
                "imported_at": versions[item.dataset_version_id].imported_at,
            }
            for item in records
        ], total

    async def rename(self, dataset_id: UUID, name: str) -> CMDBDatasetModel:
        dataset = await self._existing_dataset(dataset_id)
        dataset.name = name.strip()
        dataset.updated_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(dataset)
        return dataset

    async def retire(self, dataset_id: UUID) -> CMDBDatasetModel:
        dataset = await self._existing_dataset(dataset_id)
        dataset.status = "retired"
        dataset.retired_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(dataset)
        return dataset

    async def delete(self, dataset_id: UUID) -> None:
        dataset = await self._existing_dataset(dataset_id)
        dataset.status = "deleted"
        dataset.deleted_at = datetime.now(UTC)
        await self.session.commit()

    async def _existing_dataset(self, dataset_id: UUID) -> CMDBDatasetModel:
        dataset = await self.session.get(CMDBDatasetModel, dataset_id)
        if not dataset or dataset.deleted_at:
            raise CMDBError("DATASET_NOT_FOUND", "The dataset was not found.", 404)
        return dataset

    async def _version(self, version_id: UUID) -> CMDBDatasetVersionModel:
        version = await self.session.get(CMDBDatasetVersionModel, version_id)
        if not version:
            raise CMDBError("VERSION_NOT_FOUND", "The dataset version was not found.", 404)
        return version
