"""Pydantic v2 schemas for Administration and System Settings (Phase 118).

Enforces:
- Separation of platform-wide system settings (Super Admin) and department settings.
- Safe serialization with zero secrets, tokens, or credential leakage.
- Strict update bounds preventing arbitrary configuration alteration or privilege escalation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SystemSettingsRead(BaseModel):
    """System-level operational configuration and status (Super Admin only)."""

    model_config = ConfigDict(from_attributes=True)

    environment: str = Field(..., description="Active runtime environment.")
    app_version: str = Field(..., description="System software version.")
    log_level: str = Field(..., description="Current logging severity level.")
    cors_allowed_origins: list[str] = Field(..., description="Allowlisted CORS origins.")
    auth_access_token_expire_minutes: int = Field(
        ..., description="Access token expiration window in minutes."
    )
    auth_refresh_token_expire_days: int = Field(
        ..., description="Refresh token expiration window in days."
    )
    biometric_matching_enabled: bool = Field(
        default=False,
        description="Permanently disabled automated biometric matching flag.",
    )
    maintenance_mode: bool = Field(
        default=False, description="Institutional maintenance mode state."
    )
    system_announcement: str | None = Field(
        None, description="System-wide institutional announcement banner."
    )
    database_status: str = Field(
        default="configured_redacted", description="Database connection health indicator."
    )
    redis_status: str = Field(
        default="configured_redacted", description="Redis cache health indicator."
    )
    storage_endpoint_url_redacted: str = Field(..., description="Object storage endpoint URL.")
    storage_bucket_name: str = Field(..., description="Evidence storage bucket.")
    storage_region: str = Field(..., description="Object storage region.")
    ai_provider: str = Field(..., description="AI analysis provider.")
    max_upload_size_bytes: int = Field(..., description="Max upload file size limit.")
    allowed_evidence_mime_types: list[str] = Field(..., description="Permitted evidence MIME types.")


class SystemSettingsUpdate(BaseModel):
    """Payload for updating operational system settings (Super Admin only)."""

    model_config = ConfigDict(extra="forbid")

    maintenance_mode: bool | None = Field(None, description="Toggle institutional maintenance mode.")
    system_announcement: str | None = Field(
        None, max_length=500, description="Update or clear system announcement."
    )


class DepartmentSettingsRead(BaseModel):
    """Department-specific settings and operational parameters."""

    model_config = ConfigDict(from_attributes=True)

    department_id: UUID = Field(..., description="Department unique identifier.")
    code: str = Field(..., description="Normalized department code.")
    name: str = Field(..., description="Full department name.")
    description: str | None = Field(None, description="Department description.")
    is_active: bool = Field(..., description="Department active status.")
    contact_email: str | None = Field(None, description="Department administrative contact email.")
    retention_period_days: int = Field(
        default=365, description="Evidence and incident retention threshold in days."
    )
    max_active_cases_per_investigator: int = Field(
        default=10, description="Workload ceiling per investigator."
    )
    require_two_party_case_closure: bool = Field(
        default=True, description="Enforce independent secondary approval before closing cases."
    )


class DepartmentSettingsUpdate(BaseModel):
    """Payload for updating department settings (Dept Admin or Super Admin)."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(None, max_length=1000, description="Department description.")
    contact_email: str | None = Field(None, max_length=255, description="Administrative contact email.")
    retention_period_days: int | None = Field(
        None, ge=30, le=3650, description="Retention threshold (30 to 3650 days)."
    )
    max_active_cases_per_investigator: int | None = Field(
        None, ge=1, le=50, description="Workload ceiling (1 to 50 active cases)."
    )
    require_two_party_case_closure: bool | None = Field(
        None, description="Require secondary approval for case closure."
    )


class DepartmentListItem(BaseModel):
    """Department summary entry for administrative management."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Department UUID.")
    code: str = Field(..., description="Department code.")
    name: str = Field(..., description="Department name.")
    description: str | None = Field(None, description="Department description.")
    is_active: bool = Field(..., description="Active status.")
    created_at: datetime | None = Field(None, description="Creation timestamp.")
