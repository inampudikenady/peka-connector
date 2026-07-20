import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

ASSOCIATED_DATA = b"peka-connector-secret-v1"
KEY_CHECK_VALUE = "peka-encryption-key-valid"


class SecretKeyUnavailableError(Exception):
    pass


class SecretDecryptionError(Exception):
    pass


class SecretEncryptionService:
    """AES-256-GCM authenticated encryption derived from a deployment secret."""

    def __init__(self, deployment_key: SecretStr | None) -> None:
        self._key = (
            hashlib.sha256(deployment_key.get_secret_value().encode("utf-8")).digest()
            if deployment_key
            else None
        )

    @property
    def ready(self) -> bool:
        return self._key is not None

    def encrypt(self, plaintext: str) -> str:
        key = self._require_key()
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), ASSOCIATED_DATA)
        return "v1:" + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, encrypted: str) -> str:
        key = self._require_key()
        try:
            version, encoded = encrypted.split(":", 1)
            if version != "v1":
                raise ValueError("Unsupported encrypted value version")
            payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
            return AESGCM(key).decrypt(payload[:12], payload[12:], ASSOCIATED_DATA).decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
            raise SecretDecryptionError(
                "Stored connector credentials cannot be decrypted with the deployment key"
            ) from exc

    def create_key_check(self) -> str:
        return self.encrypt(KEY_CHECK_VALUE)

    def validate_key_check(self, encrypted_check: str) -> None:
        if self.decrypt(encrypted_check) != KEY_CHECK_VALUE:
            raise SecretDecryptionError("Deployment encryption key validation failed")

    def _require_key(self) -> bytes:
        if self._key is None:
            raise SecretKeyUnavailableError("PEKA_ENCRYPTION_KEY is required")
        return self._key
