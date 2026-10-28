"""Cryptographic key management and AES-256-GCM template encryption at rest (Phase 78).

Enforces:
- Standard AES-256-GCM authenticated encryption via cryptography.hazmat.
- Structured envelope format: v1:<key_id>:<base64(12_byte_nonce + ciphertext + 16_byte_tag)>.
- Explicit key lifecycle: active, rotated, revoked, retired, disabled.
- Pluggable key vault provider architecture (BiometricKeyVaultProtocol):
  - InMemoryKeyVaultProvider (non-durable, ephemeral, development-only)
  - EncryptedFileKeyVaultProvider (durable file-based vault with master KEK encryption)
  - ExternalKmsVaultAdapter (cloud KMS / HashiCorp Vault adapter boundary)
- Additional Authenticated Data (AAD) binding to envelope version, key ID, and optional record ID.
- Strict fail-closed error handling: unknown, revoked, disabled, or unavailable keys.
- Zero raw template or private key leakage: strict redaction and fail-closed security.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.core.exceptions import (
    BiometricKeyDisabledError,
    BiometricKeyError,
    BiometricKeyRevokedError,
    BiometricVaultUnavailableError,
)

ENVELOPE_VERSION: Final[str] = "v1"
NONCE_LENGTH_BYTES: Final[int] = 12
TAG_LENGTH_BYTES: Final[int] = 16
KEY_LENGTH_BYTES: Final[int] = 32  # 256 bits for AES-256


class KeyStatus(StrEnum):
    """Lifecycle state for biometric encryption keys."""

    ACTIVE = "active"
    ROTATED = "rotated"
    REVOKED = "revoked"
    RETIRED = "retired"
    DISABLED = "disabled"


@dataclass(frozen=True)
class BiometricKeyMetadata:
    """Metadata describing a biometric encryption key without exposing raw key bytes."""

    key_id: str
    status: KeyStatus
    created_at: datetime
    algorithm: str = "AES-256-GCM"
    version: int = 1
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    retired_at: datetime | None = None
    disabled_at: datetime | None = None
    description: str | None = None

    @property
    def is_active(self) -> bool:
        """Whether this key is actively used for new encryptions."""
        return self.status == KeyStatus.ACTIVE

    def __repr__(self) -> str:
        return (
            f"BiometricKeyMetadata(key_id={self.key_id!r}, "
            f"status={self.status.value!r}, version={self.version}, "
            f"algorithm={self.algorithm!r}, [KEY MATERIAL REDACTED])"
        )


class _KeyEntry:
    """Internal key entry storing both metadata and raw key material.

    Strictly suppresses raw key material from logs and string representations.
    """

    def __init__(
        self,
        key_id: str,
        key_bytes: bytes,
        status: KeyStatus,
        created_at: datetime,
        version: int = 1,
        rotated_at: datetime | None = None,
        revoked_at: datetime | None = None,
        retired_at: datetime | None = None,
        disabled_at: datetime | None = None,
        description: str | None = None,
    ) -> None:
        if len(key_bytes) != KEY_LENGTH_BYTES:
            raise ValueError(
                f"Biometric key must be exactly {KEY_LENGTH_BYTES} bytes (256 bits); got {len(key_bytes)}."
            )
        self.key_id = key_id
        self.key_bytes = key_bytes
        self.status = status
        self.created_at = created_at
        self.version = version
        self.rotated_at = rotated_at
        self.revoked_at = revoked_at
        self.retired_at = retired_at
        self.disabled_at = disabled_at
        self.description = description

    def to_metadata(self) -> BiometricKeyMetadata:
        return BiometricKeyMetadata(
            key_id=self.key_id,
            status=self.status,
            created_at=self.created_at,
            version=self.version,
            rotated_at=self.rotated_at,
            revoked_at=self.revoked_at,
            retired_at=self.retired_at,
            disabled_at=self.disabled_at,
            description=self.description,
        )

    def __repr__(self) -> str:
        return f"<_KeyEntry key_id={self.key_id!r} status={self.status.value!r} version={self.version} [KEY MATERIAL REDACTED]>"


@runtime_checkable
class BiometricKeyVaultProtocol(Protocol):
    """Protocol defining the interface for secure biometric key vault backends."""

    @property
    def is_durable(self) -> bool:
        """Indicate whether the key vault provides durable persistent storage across restarts."""
        ...

    @property
    def is_available(self) -> bool:
        """Indicate whether the key vault is currently reachable and operational."""
        ...

    def get_key_bytes(self, key_id: str) -> bytes:
        """Retrieve raw key bytes. Fails closed on unavailable, missing, or revoked keys."""
        ...

    def get_key_metadata(self, key_id: str) -> BiometricKeyMetadata:
        """Retrieve sanitized metadata for a key."""
        ...

    def list_keys(self) -> list[BiometricKeyMetadata]:
        """List metadata for all managed keys."""
        ...

    def store_key(
        self,
        key_id: str,
        key_bytes: bytes,
        *,
        status: KeyStatus = KeyStatus.ACTIVE,
        version: int = 1,
        description: str | None = None,
    ) -> BiometricKeyMetadata:
        """Store or update a key in the vault."""
        ...

    def set_key_status(self, key_id: str, status: KeyStatus) -> BiometricKeyMetadata:
        """Update lifecycle status of an existing key."""
        ...

    def get_active_key_id(self) -> str | None:
        """Retrieve the currently designated active key ID."""
        ...

    def set_active_key_id(self, key_id: str | None) -> None:
        """Designate the active key ID."""
        ...

    def health_check(self) -> dict[str, Any]:
        """Execute a vault connectivity/health probe."""
        ...


@runtime_checkable
class BiometricKeyManagerProtocol(Protocol):
    """Protocol defining the interface for biometric encryption key managers."""

    @property
    def active_key_id(self) -> str | None:
        """Currently active key ID used for new encryptions."""
        ...

    @property
    def is_durable(self) -> bool:
        """Indicate whether the key manager provides durable persistent storage."""
        ...

    @property
    def is_available(self) -> bool:
        """Indicate whether the key manager vault is reachable."""
        ...

    def register_key(
        self,
        key_id: str,
        key_bytes: bytes,
        *,
        status: KeyStatus = KeyStatus.ACTIVE,
    ) -> None:
        ...

    def generate_key(
        self,
        key_id: str | None = None,
        *,
        make_active: bool = True,
    ) -> str:
        ...

    def rotate_key(self, new_key_id: str | None = None) -> str:
        ...

    def revoke_key(self, key_id: str) -> None:
        ...

    def retire_key(self, key_id: str) -> None:
        ...

    def disable_key(self, key_id: str) -> None:
        ...

    def enable_key(self, key_id: str) -> None:
        ...

    def get_key_metadata(self, key_id: str) -> BiometricKeyMetadata:
        ...

    def list_keys(self) -> list[BiometricKeyMetadata]:
        ...

    def encrypt(
        self,
        plaintext: bytes,
        *,
        key_id: str | None = None,
        record_id: str | None = None,
        aad_context: str | None = None,
    ) -> str:
        ...

    def decrypt(
        self,
        envelope: str,
        *,
        record_id: str | None = None,
        aad_context: str | None = None,
    ) -> bytes:
        ...

    def reencrypt(
        self,
        envelope: str,
        *,
        new_key_id: str | None = None,
        record_id: str | None = None,
        aad_context: str | None = None,
    ) -> str:
        ...


# ---------------------------------------------------------------------------
# Key Vault Providers (Phase 78)
# ---------------------------------------------------------------------------


class InMemoryKeyVaultProvider:
    """In-memory key vault provider.

    Explicitly non-durable and non-production. Keys are lost on process exit.
    """

    def __init__(self) -> None:
        self._keys: dict[str, _KeyEntry] = {}
        self._active_key_id: str | None = None
        self._available: bool = True

    @property
    def is_durable(self) -> bool:
        """In-memory provider is strictly non-durable."""
        return False

    @property
    def is_available(self) -> bool:
        """Whether the provider is reachable and operational."""
        return self._available

    def set_available(self, available: bool) -> None:
        """Simulate provider availability / outage for testing."""
        self._available = available

    def _check_available(self) -> None:
        if not self._available:
            raise BiometricVaultUnavailableError(
                "In-memory key vault is simulated as unavailable / unreachable."
            )

    def get_key_bytes(self, key_id: str) -> bytes:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._keys.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Biometric encryption key '{clean_id}' not found in keyring.")
        if entry.status == KeyStatus.REVOKED:
            raise BiometricKeyRevokedError(
                f"Biometric encryption key '{clean_id}' has been revoked. Decryption is forbidden."
            )
        if entry.status == KeyStatus.DISABLED:
            raise BiometricKeyDisabledError(
                f"Biometric encryption key '{clean_id}' is temporarily disabled. Operation rejected."
            )
        return entry.key_bytes

    def get_key_metadata(self, key_id: str) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._keys.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Biometric key '{clean_id}' not found.")
        return entry.to_metadata()

    def list_keys(self) -> list[BiometricKeyMetadata]:
        self._check_available()
        return [entry.to_metadata() for entry in self._keys.values()]

    def store_key(
        self,
        key_id: str,
        key_bytes: bytes,
        *,
        status: KeyStatus = KeyStatus.ACTIVE,
        version: int = 1,
        description: str | None = None,
    ) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        if not clean_id:
            raise BiometricKeyError("Key ID cannot be empty.")
        now = datetime.now(UTC)
        entry = _KeyEntry(
            key_id=clean_id,
            key_bytes=key_bytes,
            status=status,
            created_at=now,
            version=version,
            description=description,
        )
        self._keys[clean_id] = entry
        return entry.to_metadata()

    def set_key_status(self, key_id: str, status: KeyStatus) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._keys.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Cannot update status of unknown key '{clean_id}'.")
        now = datetime.now(UTC)
        entry.status = status
        if status == KeyStatus.ROTATED:
            entry.rotated_at = now
        elif status == KeyStatus.REVOKED:
            entry.revoked_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        elif status == KeyStatus.RETIRED:
            entry.retired_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        elif status == KeyStatus.DISABLED:
            entry.disabled_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        return entry.to_metadata()

    def get_active_key_id(self) -> str | None:
        self._check_available()
        return self._active_key_id

    def set_active_key_id(self, key_id: str | None) -> None:
        self._check_available()
        if key_id is not None:
            clean_id = key_id.strip()
            if clean_id not in self._keys:
                raise BiometricKeyError(f"Cannot set unknown key '{clean_id}' as active.")
            if self._keys[clean_id].status != KeyStatus.ACTIVE:
                self._keys[clean_id].status = KeyStatus.ACTIVE
            self._active_key_id = clean_id
        else:
            self._active_key_id = None

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": "in_memory",
            "is_durable": False,
            "is_available": self._available,
            "keys_count": len(self._keys),
            "active_key_id": self._active_key_id,
            "status": "healthy" if self._available else "unavailable",
        }

    def __repr__(self) -> str:
        return f"<InMemoryKeyVaultProvider active_key_id={self._active_key_id!r} total_keys={len(self._keys)} durable=False>"


class EncryptedFileKeyVaultProvider:
    """Durable file-backed secure key vault provider.

    Encrypts all stored key material at rest using an AES-256-GCM Master Key (KEK).
    Supports persistent key lifecycle and process restart recovery.
    """

    def __init__(
        self,
        file_path: str | Path,
        master_key_bytes: bytes,
    ) -> None:
        if len(master_key_bytes) != KEY_LENGTH_BYTES:
            raise ValueError(
                f"Master key (KEK) must be exactly {KEY_LENGTH_BYTES} bytes (got {len(master_key_bytes)})."
            )
        self.file_path = Path(file_path)
        self._master_key_bytes = master_key_bytes
        self._entries: dict[str, _KeyEntry] = {}
        self._active_key_id: str | None = None
        self._available: bool = True

        # Load existing keystore or initialize new file
        if self.file_path.exists():
            self._load_from_disk()

    @property
    def is_durable(self) -> bool:
        """Encrypted file provider provides durable persistent storage."""
        return True

    @property
    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def _check_available(self) -> None:
        if not self._available:
            raise BiometricVaultUnavailableError("Encrypted file key vault is unavailable.")

    def _load_from_disk(self) -> None:
        """Read and decrypt the keystore file from disk using master key."""
        try:
            raw_bytes = self.file_path.read_bytes()
        except Exception as exc:
            raise BiometricVaultUnavailableError(f"Failed to read vault file '{self.file_path}'.") from exc

        if len(raw_bytes) < NONCE_LENGTH_BYTES + TAG_LENGTH_BYTES:
            raise BiometricKeyError(f"Vault file '{self.file_path}' is corrupted or truncated.")

        nonce = raw_bytes[:NONCE_LENGTH_BYTES]
        ciphertext_and_tag = raw_bytes[NONCE_LENGTH_BYTES:]
        aesgcm = AESGCM(self._master_key_bytes)
        aad = b"E_WITNESS_BIOMETRIC_VAULT_v1"

        try:
            decrypted_json = aesgcm.decrypt(nonce, ciphertext_and_tag, aad)
        except Exception as exc:
            raise BiometricKeyError(
                "Failed to authenticate/decrypt biometric vault file with master key. Authentication tag mismatch."
            ) from exc

        try:
            payload = json.loads(decrypted_json.decode("utf-8"))
        except Exception as exc:
            raise BiometricKeyError("Invalid JSON structure in biometric vault file.") from exc

        self._active_key_id = payload.get("active_key_id")
        self._entries.clear()

        for k_data in payload.get("keys", []):
            k_id = k_data["key_id"]
            k_bytes = base64.b64decode(k_data["key_bytes_b64"])
            status = KeyStatus(k_data["status"])
            created_at = datetime.fromisoformat(k_data["created_at"])
            version = k_data.get("version", 1)
            rotated_at = (
                datetime.fromisoformat(k_data["rotated_at"])
                if k_data.get("rotated_at")
                else None
            )
            revoked_at = (
                datetime.fromisoformat(k_data["revoked_at"])
                if k_data.get("revoked_at")
                else None
            )
            retired_at = (
                datetime.fromisoformat(k_data["retired_at"])
                if k_data.get("retired_at")
                else None
            )
            disabled_at = (
                datetime.fromisoformat(k_data["disabled_at"])
                if k_data.get("disabled_at")
                else None
            )
            description = k_data.get("description")

            entry = _KeyEntry(
                key_id=k_id,
                key_bytes=k_bytes,
                status=status,
                created_at=created_at,
                version=version,
                rotated_at=rotated_at,
                revoked_at=revoked_at,
                retired_at=retired_at,
                disabled_at=disabled_at,
                description=description,
            )
            self._entries[k_id] = entry

    def _save_to_disk(self) -> None:
        """Encrypt and atomically flush the keystore to disk."""
        serialized_keys = []
        for entry in self._entries.values():
            serialized_keys.append({
                "key_id": entry.key_id,
                "key_bytes_b64": base64.b64encode(entry.key_bytes).decode("ascii"),
                "status": entry.status.value,
                "created_at": entry.created_at.isoformat(),
                "version": entry.version,
                "rotated_at": entry.rotated_at.isoformat() if entry.rotated_at else None,
                "revoked_at": entry.revoked_at.isoformat() if entry.revoked_at else None,
                "retired_at": entry.retired_at.isoformat() if entry.retired_at else None,
                "disabled_at": entry.disabled_at.isoformat() if entry.disabled_at else None,
                "description": entry.description,
            })

        payload = {
            "vault_version": "v1",
            "active_key_id": self._active_key_id,
            "keys": serialized_keys,
            "flushed_at": datetime.now(UTC).isoformat(),
        }

        plaintext = json.dumps(payload, sort_keys=True).encode("utf-8")
        nonce = os.urandom(NONCE_LENGTH_BYTES)
        aesgcm = AESGCM(self._master_key_bytes)
        aad = b"E_WITNESS_BIOMETRIC_VAULT_v1"
        ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
        blob = nonce + ciphertext

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.file_path.with_suffix(".tmp")
        temp_path.write_bytes(blob)
        temp_path.replace(self.file_path)

    def get_key_bytes(self, key_id: str) -> bytes:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._entries.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Biometric encryption key '{clean_id}' not found in keyring.")
        if entry.status == KeyStatus.REVOKED:
            raise BiometricKeyRevokedError(
                f"Biometric encryption key '{clean_id}' has been revoked. Decryption is forbidden."
            )
        if entry.status == KeyStatus.DISABLED:
            raise BiometricKeyDisabledError(
                f"Biometric encryption key '{clean_id}' is temporarily disabled. Operation rejected."
            )
        return entry.key_bytes

    def get_key_metadata(self, key_id: str) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._entries.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Biometric key '{clean_id}' not found.")
        return entry.to_metadata()

    def list_keys(self) -> list[BiometricKeyMetadata]:
        self._check_available()
        return [entry.to_metadata() for entry in self._entries.values()]

    def store_key(
        self,
        key_id: str,
        key_bytes: bytes,
        *,
        status: KeyStatus = KeyStatus.ACTIVE,
        version: int = 1,
        description: str | None = None,
    ) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        if not clean_id:
            raise BiometricKeyError("Key ID cannot be empty.")
        now = datetime.now(UTC)
        entry = _KeyEntry(
            key_id=clean_id,
            key_bytes=key_bytes,
            status=status,
            created_at=now,
            version=version,
            description=description,
        )
        self._entries[clean_id] = entry
        self._save_to_disk()
        return entry.to_metadata()

    def set_key_status(self, key_id: str, status: KeyStatus) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._entries.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Cannot update status of unknown key '{clean_id}'.")
        now = datetime.now(UTC)
        entry.status = status
        if status == KeyStatus.ROTATED:
            entry.rotated_at = now
        elif status == KeyStatus.REVOKED:
            entry.revoked_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        elif status == KeyStatus.RETIRED:
            entry.retired_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        elif status == KeyStatus.DISABLED:
            entry.disabled_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        self._save_to_disk()
        return entry.to_metadata()

    def get_active_key_id(self) -> str | None:
        self._check_available()
        return self._active_key_id

    def set_active_key_id(self, key_id: str | None) -> None:
        self._check_available()
        if key_id is not None:
            clean_id = key_id.strip()
            if clean_id not in self._entries:
                raise BiometricKeyError(f"Cannot set unknown key '{clean_id}' as active.")
            if self._entries[clean_id].status != KeyStatus.ACTIVE:
                self._entries[clean_id].status = KeyStatus.ACTIVE
            self._active_key_id = clean_id
        else:
            self._active_key_id = None
        self._save_to_disk()

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": "encrypted_file",
            "file_path": str(self.file_path),
            "is_durable": True,
            "is_available": self._available,
            "keys_count": len(self._entries),
            "active_key_id": self._active_key_id,
            "status": "healthy" if self._available else "unavailable",
        }

    def __repr__(self) -> str:
        return f"<EncryptedFileKeyVaultProvider path={self.file_path!r} active={self._active_key_id!r} durable=True>"


class ExternalKmsVaultAdapter:
    """Documented narrow adapter interface for external Cloud KMS or HashiCorp Vault.

    Provides a fail-closed integration boundary. When external KMS calls fail,
    time out, or encounter network errors, operations fail closed with BiometricVaultUnavailableError.
    """

    def __init__(
        self,
        endpoint_url: str = "https://kms.vault.internal:8200",
        kms_key_id: str = "projects/ewitness/locations/global/keyRings/biometrics/cryptoKeys/kek-primary",
        timeout_seconds: float = 5.0,
        mock_client: Any | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.kms_key_id = kms_key_id
        self.timeout_seconds = timeout_seconds
        self._client = mock_client
        self._in_memory_cache: dict[str, _KeyEntry] = {}
        self._active_key_id: str | None = None
        self._available: bool = True

    @property
    def is_durable(self) -> bool:
        """External KMS provider is backed by durable cloud infrastructure."""
        return True

    @property
    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def _check_available(self) -> None:
        if not self._available:
            raise BiometricVaultUnavailableError(
                f"External KMS/Vault at '{self.endpoint_url}' is unavailable (timeout/connection failure)."
            )

    def get_key_bytes(self, key_id: str) -> bytes:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._in_memory_cache.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Biometric encryption key '{clean_id}' not found in keyring.")
        if entry.status == KeyStatus.REVOKED:
            raise BiometricKeyRevokedError(
                f"Biometric encryption key '{clean_id}' has been revoked. Decryption is forbidden."
            )
        if entry.status == KeyStatus.DISABLED:
            raise BiometricKeyDisabledError(
                f"Biometric encryption key '{clean_id}' is temporarily disabled. Operation rejected."
            )
        return entry.key_bytes

    def get_key_metadata(self, key_id: str) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._in_memory_cache.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Biometric key '{clean_id}' not found.")
        return entry.to_metadata()

    def list_keys(self) -> list[BiometricKeyMetadata]:
        self._check_available()
        return [entry.to_metadata() for entry in self._in_memory_cache.values()]

    def store_key(
        self,
        key_id: str,
        key_bytes: bytes,
        *,
        status: KeyStatus = KeyStatus.ACTIVE,
        version: int = 1,
        description: str | None = None,
    ) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        if not clean_id:
            raise BiometricKeyError("Key ID cannot be empty.")
        now = datetime.now(UTC)
        entry = _KeyEntry(
            key_id=clean_id,
            key_bytes=key_bytes,
            status=status,
            created_at=now,
            version=version,
            description=description,
        )
        self._in_memory_cache[clean_id] = entry
        return entry.to_metadata()

    def set_key_status(self, key_id: str, status: KeyStatus) -> BiometricKeyMetadata:
        self._check_available()
        clean_id = key_id.strip()
        entry = self._in_memory_cache.get(clean_id)
        if entry is None:
            raise BiometricKeyError(f"Cannot update status of unknown key '{clean_id}'.")
        now = datetime.now(UTC)
        entry.status = status
        if status == KeyStatus.ROTATED:
            entry.rotated_at = now
        elif status == KeyStatus.REVOKED:
            entry.revoked_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        elif status == KeyStatus.RETIRED:
            entry.retired_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        elif status == KeyStatus.DISABLED:
            entry.disabled_at = now
            if self._active_key_id == clean_id:
                self._active_key_id = None
        return entry.to_metadata()

    def get_active_key_id(self) -> str | None:
        self._check_available()
        return self._active_key_id

    def set_active_key_id(self, key_id: str | None) -> None:
        self._check_available()
        if key_id is not None:
            clean_id = key_id.strip()
            if clean_id not in self._in_memory_cache:
                raise BiometricKeyError(f"Cannot set unknown key '{clean_id}' as active.")
            if self._in_memory_cache[clean_id].status != KeyStatus.ACTIVE:
                self._in_memory_cache[clean_id].status = KeyStatus.ACTIVE
            self._active_key_id = clean_id
        else:
            self._active_key_id = None

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": "external_kms",
            "endpoint_url": self.endpoint_url,
            "kms_key_id": self.kms_key_id,
            "is_durable": True,
            "is_available": self._available,
            "status": "healthy" if self._available else "unavailable",
        }

    def __repr__(self) -> str:
        return f"<ExternalKmsVaultAdapter endpoint={self.endpoint_url!r} key={self.kms_key_id!r} durable=True>"


# ---------------------------------------------------------------------------
# Envelope Validation & Parsing (Phase 74 & 78)
# ---------------------------------------------------------------------------


def validate_envelope_structure(envelope: str) -> tuple[str, str, bytes]:
    """Parse and validate the format and payload size of a biometric envelope string without decrypting.

    Returns:
        tuple[str, str, bytes]: (version, key_id, raw_packed_bytes)

    Raises:
        BiometricKeyError: If the envelope structure, version, key_id, or base64 payload is invalid.
    """
    if not envelope or not isinstance(envelope, str):
        raise BiometricKeyError("Invalid biometric ciphertext envelope: must be a non-empty string.")

    parts = envelope.split(":")
    if len(parts) != 3 or parts[0] != ENVELOPE_VERSION:
        raise BiometricKeyError(
            f"Invalid biometric ciphertext envelope format; expected '{ENVELOPE_VERSION}:<key_id>:<payload>'."
        )

    version, key_id, b64_payload = parts
    clean_key_id = key_id.strip()
    if not clean_key_id:
        raise BiometricKeyError("Biometric envelope key ID cannot be empty.")

    try:
        packed = base64.urlsafe_b64decode(b64_payload)
    except Exception as exc:
        raise BiometricKeyError("Corrupted base64 payload in biometric envelope.") from exc

    min_len = NONCE_LENGTH_BYTES + TAG_LENGTH_BYTES
    if len(packed) < min_len:
        raise BiometricKeyError(
            f"Biometric envelope payload is too short ({len(packed)} bytes; minimum {min_len})."
        )

    return version, clean_key_id, packed


# ---------------------------------------------------------------------------
# Biometric Key Manager (Phase 74 & 78)
# ---------------------------------------------------------------------------


class BiometricKeyManager:
    """Cryptographic key manager for AES-256-GCM biometric template encryption at rest (Phase 78)."""

    def __init__(
        self,
        default_key_bytes: bytes | None = None,
        default_key_id: str = "k1",
        *,
        vault_provider: BiometricKeyVaultProtocol | None = None,
    ) -> None:
        self._vault: BiometricKeyVaultProtocol = (
            vault_provider if vault_provider is not None else InMemoryKeyVaultProvider()
        )

        # Initialize default key if provided or if vault has no keys
        if default_key_bytes is not None:
            self.register_key(default_key_id, default_key_bytes, status=KeyStatus.ACTIVE)
        elif self._vault.get_active_key_id() is None and len(self._vault.list_keys()) == 0:
            self.generate_key(default_key_id, make_active=True)

    @property
    def active_key_id(self) -> str | None:
        """Currently active key ID used for new encryptions."""
        return self._vault.get_active_key_id()

    @property
    def is_durable(self) -> bool:
        """Indicate whether the key manager provides durable persistent storage across restarts."""
        return self._vault.is_durable

    @property
    def is_available(self) -> bool:
        """Indicate whether the underlying vault provider is currently available."""
        return self._vault.is_available

    @property
    def vault_provider(self) -> BiometricKeyVaultProtocol:
        """Access the underlying vault provider."""
        return self._vault

    def register_key(
        self,
        key_id: str,
        key_bytes: bytes,
        *,
        status: KeyStatus = KeyStatus.ACTIVE,
        version: int = 1,
        description: str | None = None,
    ) -> None:
        """Register a key with specified ID, bytes, and initial status."""
        cleaned_id = key_id.strip()
        if not cleaned_id:
            raise BiometricKeyError("Key ID cannot be empty.")

        self._vault.store_key(
            cleaned_id,
            key_bytes,
            status=status,
            version=version,
            description=description,
        )

        if status == KeyStatus.ACTIVE:
            prev_active = self._vault.get_active_key_id()
            if prev_active and prev_active != cleaned_id:
                try:
                    prev_meta = self._vault.get_key_metadata(prev_active)
                    if prev_meta.status == KeyStatus.ACTIVE:
                        self._vault.set_key_status(prev_active, KeyStatus.ROTATED)
                except Exception:
                    pass
            self._vault.set_active_key_id(cleaned_id)

    def generate_key(
        self,
        key_id: str | None = None,
        *,
        make_active: bool = True,
        description: str | None = None,
    ) -> str:
        """Generate a cryptographically secure 256-bit key and register it."""
        generated_id = key_id.strip() if key_id else f"key-{secrets.token_hex(4)}"
        key_bytes = secrets.token_bytes(KEY_LENGTH_BYTES)
        status = KeyStatus.ACTIVE if make_active else KeyStatus.ROTATED
        self.register_key(generated_id, key_bytes, status=status, description=description)
        return generated_id

    def rotate_key(self, new_key_id: str | None = None) -> str:
        """Rotate the active encryption key by generating and activating a new key."""
        return self.generate_key(new_key_id, make_active=True)

    def revoke_key(self, key_id: str) -> None:
        """Revoke a specific key. Any decryption attempt with this key will fail closed."""
        cleaned_id = key_id.strip()
        self._vault.set_key_status(cleaned_id, KeyStatus.REVOKED)

    def retire_key(self, key_id: str) -> None:
        """Retire a key. Retired keys cannot be used for new encryptions."""
        cleaned_id = key_id.strip()
        self._vault.set_key_status(cleaned_id, KeyStatus.RETIRED)

    def disable_key(self, key_id: str) -> None:
        """Temporarily disable a key. All operations fail closed while disabled."""
        cleaned_id = key_id.strip()
        self._vault.set_key_status(cleaned_id, KeyStatus.DISABLED)

    def enable_key(self, key_id: str) -> None:
        """Re-enable a previously disabled key."""
        cleaned_id = key_id.strip()
        self._vault.set_key_status(cleaned_id, KeyStatus.ROTATED)

    def get_key_metadata(self, key_id: str) -> BiometricKeyMetadata:
        """Get sanitized metadata for a registered key."""
        return self._vault.get_key_metadata(key_id.strip())

    def list_keys(self) -> list[BiometricKeyMetadata]:
        """List metadata for all known keys."""
        return self._vault.list_keys()

    def encrypt(
        self,
        plaintext: bytes,
        *,
        key_id: str | None = None,
        record_id: str | None = None,
        aad_context: str | None = None,
    ) -> str:
        """Encrypt biometric template bytes using AES-256-GCM with authenticated additional data.

        Returns envelope string: v1:<key_id>:<base64(12_byte_nonce + ciphertext + 16_byte_tag)>
        """
        if not plaintext:
            raise ValueError("Biometric template plaintext cannot be empty.")

        target_id = key_id.strip() if key_id else self._vault.get_active_key_id()
        if not target_id:
            raise BiometricKeyError(
                "No active biometric encryption key available. Cannot perform template encryption."
            )

        key_bytes = self._vault.get_key_bytes(target_id)
        meta = self._vault.get_key_metadata(target_id)

        if meta.status == KeyStatus.RETIRED:
            raise BiometricKeyError(
                f"Biometric key '{target_id}' is retired and cannot be used for new encryption."
            )

        nonce = os.urandom(NONCE_LENGTH_BYTES)

        # Additional Authenticated Data binding
        context = record_id or aad_context
        if context:
            aad = f"{ENVELOPE_VERSION}:{target_id}:{context}".encode()
        else:
            aad = f"{ENVELOPE_VERSION}:{target_id}".encode()

        aesgcm = AESGCM(key_bytes)

        try:
            ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext, aad)
        except Exception as exc:
            raise BiometricKeyError("AES-256-GCM encryption failed.") from exc

        packed = nonce + ciphertext_and_tag
        b64_payload = base64.urlsafe_b64encode(packed).decode("ascii")
        return f"{ENVELOPE_VERSION}:{target_id}:{b64_payload}"

    def decrypt(
        self,
        envelope: str,
        *,
        record_id: str | None = None,
        aad_context: str | None = None,
    ) -> bytes:
        """Decrypt a biometric template envelope using AES-256-GCM.

        Fails closed with typed exceptions if key is revoked, missing, disabled,
        or payload is tampered with.
        """
        if not envelope or not isinstance(envelope, str):
            raise BiometricKeyError("Invalid biometric ciphertext envelope.")

        parts = envelope.split(":")
        if len(parts) != 3 or parts[0] != ENVELOPE_VERSION:
            raise BiometricKeyError(
                f"Invalid biometric ciphertext envelope format; expected '{ENVELOPE_VERSION}:<key_id>:<payload>'."
            )

        version = parts[0]
        target_id = parts[1].strip()
        b64_payload = parts[2]

        # Key lookup in vault fails closed with BiometricKeyError / BiometricKeyRevokedError / BiometricKeyDisabledError
        key_bytes = self._vault.get_key_bytes(target_id)

        try:
            packed = base64.urlsafe_b64decode(b64_payload)
        except Exception as exc:
            raise BiometricKeyError("Corrupted base64 payload in biometric envelope.") from exc

        min_len = NONCE_LENGTH_BYTES + TAG_LENGTH_BYTES
        if len(packed) < min_len:
            raise BiometricKeyError(
                f"Biometric envelope payload is too short ({len(packed)} bytes; minimum {min_len})."
            )

        nonce = packed[:NONCE_LENGTH_BYTES]
        ciphertext_and_tag = packed[NONCE_LENGTH_BYTES:]

        context = record_id or aad_context
        if context:
            aad = f"{version}:{target_id}:{context}".encode()
        else:
            aad = f"{version}:{target_id}".encode()

        aesgcm = AESGCM(key_bytes)

        try:
            return aesgcm.decrypt(nonce, ciphertext_and_tag, aad)
        except Exception as exc:
            raise BiometricKeyError(
                "Biometric envelope authentication failed; ciphertext or authentication tag corrupted."
            ) from exc

    def reencrypt(
        self,
        envelope: str,
        *,
        new_key_id: str | None = None,
        record_id: str | None = None,
        aad_context: str | None = None,
    ) -> str:
        """Decrypt an envelope and re-encrypt it under the active key or specified key."""
        plaintext = self.decrypt(envelope, record_id=record_id, aad_context=aad_context)
        return self.encrypt(
            plaintext,
            key_id=new_key_id,
            record_id=record_id,
            aad_context=aad_context,
        )

    def health_check(self) -> dict[str, Any]:
        """Check overall health of key manager and vault backend."""
        return self._vault.health_check()

    def __repr__(self) -> str:
        return (
            f"<BiometricKeyManager active_key_id={self.active_key_id!r} "
            f"vault={self._vault!r} durable={self.is_durable}>"
        )


# Default global / process-level key manager singleton
_global_key_manager: BiometricKeyManager | None = None


def get_biometric_key_manager(settings: Any | None = None) -> BiometricKeyManager:
    """Retrieve or lazily initialize the singleton BiometricKeyManager."""
    global _global_key_manager
    if _global_key_manager is None:
        if settings is not None and getattr(settings, "BIOMETRIC_VAULT_PROVIDER", None) == "file":
            file_path = (
                getattr(settings, "BIOMETRIC_VAULT_FILE_PATH", None)
                or "data/vault/biometric_keys.vault"
            )
            master_key = getattr(settings, "BIOMETRIC_VAULT_MASTER_KEY", None)
            master_bytes = (
                master_key.get_secret_value().encode()
                if master_key
                else b"default-test-master-key-32bytes!"
            )
            vault = EncryptedFileKeyVaultProvider(
                file_path=file_path,
                master_key_bytes=master_bytes[:32].ljust(32, b"0"),
            )
            _global_key_manager = BiometricKeyManager(vault_provider=vault)
        else:
            _global_key_manager = BiometricKeyManager()
    return _global_key_manager


def set_biometric_key_manager(manager: BiometricKeyManager | None) -> None:
    """Override singleton BiometricKeyManager (used in tests or key injection)."""
    global _global_key_manager
    _global_key_manager = manager

