from __future__ import annotations

import asyncio
import ssl
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.infrastructure.database.models.certificate import TrustedCertificateAuthorityModel


class CertificateError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class TrustedCertificateService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def list(self) -> list[dict[str, object]]:
        certificates = list(
            (
                await self.session.scalars(
                    select(TrustedCertificateAuthorityModel).order_by(
                        TrustedCertificateAuthorityModel.name
                    )
                )
            ).all()
        )
        return [self._response(item) for item in certificates]

    async def upload(self, name: str, filename: str, content: bytes) -> dict[str, object]:
        if not name.strip():
            raise CertificateError("NAME_REQUIRED", "Certificate name is required.")
        if len(content) > 1024 * 1024:
            raise CertificateError("CERTIFICATE_TOO_LARGE", "Certificate must be 1 MB or smaller.")
        try:
            certificate = x509.load_pem_x509_certificate(content)
        except ValueError as exc:
            raise CertificateError(
                "INVALID_PEM", "The uploaded file is not a valid PEM certificate."
            ) from exc
        try:
            constraints = certificate.extensions.get_extension_for_class(
                x509.BasicConstraints
            ).value
        except x509.ExtensionNotFound as exc:
            raise CertificateError(
                "NOT_A_CERTIFICATE_AUTHORITY",
                "The certificate does not declare CA basic constraints.",
            ) from exc
        if not constraints.ca:
            raise CertificateError(
                "NOT_A_CERTIFICATE_AUTHORITY", "The uploaded certificate is not a CA certificate."
            )

        canonical_pem = certificate.public_bytes(serialization.Encoding.PEM)
        fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
        self.settings.ensure_trusted_ca_directory()
        path = self.settings.trusted_ca_root / f"{uuid4()}.pem"
        path.write_bytes(canonical_pem)
        path.chmod(0o600)
        model = TrustedCertificateAuthorityModel(
            name=name.strip(),
            original_filename=Path(filename).name[:255] or "certificate.pem",
            stored_path=str(path),
            fingerprint_sha256=fingerprint,
            subject=certificate.subject.rfc4514_string(),
            issuer=certificate.issuer.rfc4514_string(),
            not_valid_before=certificate.not_valid_before_utc,
            not_valid_after=certificate.not_valid_after_utc,
            enabled=True,
        )
        self.session.add(model)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            path.unlink(missing_ok=True)
            raise CertificateError(
                "CERTIFICATE_ALREADY_EXISTS",
                "A certificate with this name or fingerprint already exists.",
                409,
            ) from exc
        await self.session.refresh(model)
        return self._response(model)

    async def set_enabled(self, certificate_id: UUID, enabled: bool) -> dict[str, object]:
        model = await self._get(certificate_id)
        model.enabled = enabled
        await self.session.commit()
        await self.session.refresh(model)
        return self._response(model)

    async def delete(self, certificate_id: UUID) -> None:
        model = await self._get(certificate_id)
        path = Path(model.stored_path)
        await self.session.delete(model)
        await self.session.commit()
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        paths = list(
            (
                await self.session.scalars(
                    select(TrustedCertificateAuthorityModel.stored_path).where(
                        TrustedCertificateAuthorityModel.enabled.is_(True)
                    )
                )
            ).all()
        )
        for stored_path in paths:
            path = Path(stored_path)
            if not await asyncio.to_thread(path.is_file):
                raise CertificateError(
                    "TRUSTED_CA_FILE_MISSING",
                    f"Enabled trusted CA file is missing: {path.name}.",
                    503,
                )
            try:
                context.load_verify_locations(cafile=str(path))
            except ssl.SSLError as exc:
                raise CertificateError(
                    "TRUSTED_CA_INVALID",
                    f"Enabled trusted CA could not be loaded: {path.name}.",
                    503,
                ) from exc
        return context

    async def _get(self, certificate_id: UUID) -> TrustedCertificateAuthorityModel:
        model = await self.session.get(TrustedCertificateAuthorityModel, certificate_id)
        if model is None:
            raise CertificateError("CERTIFICATE_NOT_FOUND", "Certificate not found.", 404)
        return model

    @staticmethod
    def _response(item: TrustedCertificateAuthorityModel) -> dict[str, object]:
        now = datetime.now(UTC)
        return {
            "id": item.id,
            "name": item.name,
            "original_filename": item.original_filename,
            "fingerprint_sha256": item.fingerprint_sha256,
            "subject": item.subject,
            "issuer": item.issuer,
            "not_valid_before": item.not_valid_before,
            "not_valid_after": item.not_valid_after,
            "expired": item.not_valid_after < now,
            "enabled": item.enabled,
            "created_at": item.created_at,
        }
