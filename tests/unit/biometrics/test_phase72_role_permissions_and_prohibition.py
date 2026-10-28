"""Phase 72 Unit Tests: Role Permissions, Authorization Boundaries & Matching Prohibition.

Comprehensive automated verification for:
1. Configuration & Startup Guards (Default disabled, production rejection, env override prevention).
2. API & Service Authorization (Role boundaries, 401 unauthenticated, 403 denied, fail-closed matching).
3. Service-Layer Enforcement (Direct service fail-closed behavior, disabled matcher protocol).
4. Separation of Capabilities (Detection vs matching decoupling, zero 1:N routes, prohibited purposes).
5. Data Protection (Zero biometric template or similarity score leakage in read models).
"""

from __future__ import annotations

import base64
import os
import secrets
import struct
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ai_services.face_detection.detector import FaceDetectionOptions
from ai_services.face_matching.protocol import (
    DisabledFaceMatcherProvider,
    get_face_matcher,
)
from backend.app.api.dependencies import (
    get_current_principal,
    require_permission,
)
from backend.app.config.settings import Environment, Settings
from backend.app.core.authorization import (
    Permission,
    ROLE_PERMISSIONS,
    has_permission,
)
from backend.app.core.biometrics import (
    PROHIBITED_BIOMETRIC_PURPOSES,
    BiometricPurpose,
    ProhibitedBiometricPurpose,
    validate_biometric_purpose,
)
from backend.app.core.exceptions import (
    AuthenticationError,
    BiometricsDisabledError,
    PermissionDeniedError,
)
from backend.app.core.identity import RoleCode
from backend.app.models.biometrics import (
    BiometricGovernanceRecord,
)
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.schemas.biometrics import (
    FaceMatchRequest,
)
from backend.app.services.biometrics import (
    FaceDetectionService,
    FaceMatchingService,
)


def _make_unit_settings(**kwargs: Any) -> Settings:
    """Create isolated Settings instance for unit tests."""
    defaults: dict[str, Any] = {
        "_env_file": None,
        "ENVIRONMENT": "testing",
        "APP_NAME": "E-WITNESS Test",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "redis://localhost:6379/15",
        "STORAGE_ENDPOINT_URL": "https://s3.test.internal:9000",
        "STORAGE_BUCKET_NAME": "ewitness-test-bucket",
        "STORAGE_ACCESS_KEY": "test_access_key_isolated",
        "STORAGE_SECRET_KEY": "test_secret_key_isolated_value",
        "AUTH_SECRET_KEY": "test_only_signing_key_with_sufficient_length_32_plus",
        "AI_API_KEY": "test-ai-key",
        "BIOMETRIC_ANALYSIS_ENABLED": True,
        "BIOMETRIC_MATCHING_ENABLED": False,  # Mandatory Phase 72 invariant
        "BIOMETRIC_PROVIDER": "disabled",
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def _create_test_png(width: int = 128, height: int = 128, fill: int = 120) -> bytes:
    """Generate minimal valid PNG bytes for synthetic testing."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"
    payload = bytes([(fill + (i % 80)) % 256 for i in range(256)])
    idat_chunk = struct.pack(">I", len(payload)) + b"IDAT" + payload + b"\x00\x00\x00\x00"
    iend_chunk = struct.pack(">I", 0) + b"IEND" + b"\x00\x00\x00\x00"
    return sig + ihdr_chunk + idat_chunk + iend_chunk


def _create_principal(
    role_code: str = RoleCode.INVESTIGATOR.value,
    department_id: UUID | None = None,
) -> AuthenticatedPrincipal:
    """Generate mock AuthenticatedPrincipal."""
    return AuthenticatedPrincipal(
        user_id=uuid4(),
        email="test_user@ewitness.edu",
        full_name="Test Principal",
        account_status="active",
        is_active=True,
        role_code=role_code,
        department_id=department_id or uuid4(),
        session_id=uuid4(),
    )


# ===========================================================================
# Group A: Configuration and Startup Guards
# ===========================================================================


class TestPhase72ConfigurationAndStartupGuards:
    """Verify that configuration defaults, production gates, and environment parsing fail closed."""

    def test_default_matching_configuration_is_disabled(self) -> None:
        """The baseline default configuration must strictly disable matching."""
        # Verify schema field defaults
        assert Settings.model_fields["BIOMETRIC_MATCHING_ENABLED"].default is False
        assert Settings.model_fields["BIOMETRIC_ANALYSIS_ENABLED"].default is False
        assert Settings.model_fields["BIOMETRIC_DETECTION_ENABLED"].default is False
        assert Settings.model_fields["BIOMETRIC_PROVIDER"].default == "disabled"

        # Verify instantiated unit settings defaults
        settings = _make_unit_settings()
        assert settings.BIOMETRIC_MATCHING_ENABLED is False
        assert settings.BIOMETRIC_PROVIDER == "disabled"

    def test_production_environment_rejects_matching_enabled(self) -> None:
        """Attempting to enable matching in production MUST raise a ValidationError."""
        prod_kwargs = {
            "_env_file": None,
            "ENVIRONMENT": "production",
            "DATABASE_URL": "postgresql+asyncpg://app_user:V3ryC0mpl3xDbCred!9988@db.internal:5432/ewitness_prod",
            "REDIS_URL": "rediss://:V3ryC0mpl3xRedisCred!8899@redis.internal:6379/0",
            "STORAGE_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
            "STORAGE_BUCKET_NAME": "ewitness-prod-vault",
            "STORAGE_ACCESS_KEY": "AKIA" + secrets.token_hex(8).upper(),
            "STORAGE_SECRET_KEY": secrets.token_urlsafe(32),
            "AUTH_SECRET_KEY": secrets.token_urlsafe(64),
            "SECURITY_HEADERS_ENABLED": True,
            "STORAGE_USE_SSL": True,
            "ENFORCE_SSL": True,
            "CORS_ALLOWED_ORIGINS": ["https://app.ewitness.org"],
            "ALLOWED_HOSTS": ["app.ewitness.org"],
            "BIOMETRIC_MATCHING_ENABLED": True,
        }

        with pytest.raises(ValidationError) as exc_info:
            Settings(**prod_kwargs)

        assert "BIOMETRIC_MATCHING_ENABLED=True is strictly forbidden in production" in str(
            exc_info.value
        )

    def test_environment_variable_override_cannot_bypass_production_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables cannot bypass the production matching lock."""
        prod_kwargs = {
            "_env_file": None,
            "ENVIRONMENT": "production",
            "DATABASE_URL": "postgresql+asyncpg://app_user:V3ryC0mpl3xDbCred!9988@db.internal:5432/ewitness_prod",
            "REDIS_URL": "rediss://:V3ryC0mpl3xRedisCred!8899@redis.internal:6379/0",
            "STORAGE_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
            "STORAGE_BUCKET_NAME": "ewitness-prod-vault",
            "STORAGE_ACCESS_KEY": "AKIA" + secrets.token_hex(8).upper(),
            "STORAGE_SECRET_KEY": secrets.token_urlsafe(32),
            "AUTH_SECRET_KEY": secrets.token_urlsafe(64),
            "SECURITY_HEADERS_ENABLED": True,
            "STORAGE_USE_SSL": True,
            "ENFORCE_SSL": True,
            "CORS_ALLOWED_ORIGINS": ["https://app.ewitness.org"],
            "ALLOWED_HOSTS": ["app.ewitness.org"],
        }
        monkeypatch.setenv("BIOMETRIC_MATCHING_ENABLED", "true")

        with pytest.raises(ValidationError) as exc_info:
            Settings(**prod_kwargs)

        assert "BIOMETRIC_MATCHING_ENABLED=True is strictly forbidden in production" in str(
            exc_info.value
        )

    def test_tenant_opt_in_does_not_activate_matching_side_effect(self) -> None:
        """Enabling analysis or detection MUST NOT enable face matching as a side effect."""
        settings = _make_unit_settings(
            BIOMETRIC_ANALYSIS_ENABLED=True,
            BIOMETRIC_DETECTION_ENABLED=True,
            BIOMETRIC_PROVIDER="mock",
        )
        assert settings.BIOMETRIC_ANALYSIS_ENABLED is True
        assert settings.BIOMETRIC_DETECTION_ENABLED is True
        assert settings.BIOMETRIC_MATCHING_ENABLED is False  # Must remain False


# ===========================================================================
# Group B: Role-Based Access Control and Permission Boundaries
# ===========================================================================


class TestPhase72RolePermissionsMatrix:
    """Verify role-to-permission mapping boundaries for all biometric capabilities."""

    def test_student_has_only_own_reference_permissions(self) -> None:
        """Students / community members can only view and manage their own enrolled references."""
        perms = ROLE_PERMISSIONS[RoleCode.STUDENT]
        assert Permission.BIOMETRIC_REFERENCE_READ_OWN in perms
        assert Permission.BIOMETRIC_REFERENCE_MANAGE_OWN in perms
        assert Permission.BIOMETRIC_MATCHING_EXECUTE not in perms
        assert Permission.BIOMETRIC_DETECTION_EXECUTE not in perms
        assert Permission.BIOMETRIC_GOVERNANCE_REVIEW not in perms
        assert Permission.BIOMETRIC_AUDIT_READ not in perms

    def test_staff_has_only_own_reference_permissions(self) -> None:
        """Staff members lack investigative matching and detection permissions."""
        perms = ROLE_PERMISSIONS[RoleCode.STAFF]
        assert Permission.BIOMETRIC_REFERENCE_READ_OWN in perms
        assert Permission.BIOMETRIC_REFERENCE_MANAGE_OWN in perms
        assert Permission.BIOMETRIC_MATCHING_EXECUTE not in perms
        assert Permission.BIOMETRIC_DETECTION_EXECUTE not in perms

    def test_investigator_has_detection_and_review_permissions(self) -> None:
        """Investigators have operational detection and review, but no governance review."""
        perms = ROLE_PERMISSIONS[RoleCode.INVESTIGATOR]
        assert Permission.BIOMETRIC_DETECTION_EXECUTE in perms
        assert Permission.BIOMETRIC_MATCHING_EXECUTE in perms
        assert Permission.BIOMETRIC_VERIFICATION_REVIEW in perms
        assert Permission.BIOMETRIC_REFERENCE_READ_DEPT in perms
        assert Permission.BIOMETRIC_GOVERNANCE_REVIEW not in perms
        assert Permission.BIOMETRIC_CONFIG_MANAGE not in perms

    def test_dept_admin_has_departmental_governance_permissions(self) -> None:
        """Department admins have governance review and department audit read."""
        perms = ROLE_PERMISSIONS[RoleCode.DEPT_ADMIN]
        assert Permission.BIOMETRIC_GOVERNANCE_REVIEW in perms
        assert Permission.BIOMETRIC_AUDIT_READ in perms
        assert Permission.BIOMETRIC_REFERENCE_MANAGE_DEPT in perms
        assert Permission.BIOMETRIC_CONFIG_MANAGE not in perms

    def test_super_admin_has_global_biometric_permissions(self) -> None:
        """Super admins possess global configuration and governance permissions."""
        perms = ROLE_PERMISSIONS[RoleCode.SUPER_ADMIN]
        assert Permission.BIOMETRIC_CONFIG_MANAGE in perms
        assert Permission.BIOMETRIC_REFERENCE_MANAGE_GLOBAL in perms
        assert Permission.BIOMETRIC_REFERENCE_READ_GLOBAL in perms
        assert Permission.BIOMETRIC_GOVERNANCE_REVIEW in perms


# ===========================================================================
# Group C: Service-Layer Enforcement & Fail-Closed Logic
# ===========================================================================


class TestPhase72ServiceLayerEnforcement:
    """Verify service-layer authorization and matching prohibition enforcement."""

    @pytest.mark.asyncio
    async def test_direct_service_call_rejects_unauthorized_role(self) -> None:
        """A caller without BIOMETRIC_MATCHING_EXECUTE is rejected at service layer."""
        settings = _make_unit_settings(BIOMETRIC_MATCHING_ENABLED=False)
        mock_session = AsyncMock()
        service = FaceMatchingService.from_session(mock_session, settings=settings)

        student = _create_principal(role_code=RoleCode.STUDENT.value)
        req = FaceMatchRequest(
            governance_record_id=uuid4(),
            probe_image_base64=base64.b64encode(_create_test_png()).decode(),
            reference_id=uuid4(),
        )

        with pytest.raises(PermissionDeniedError) as exc_info:
            await service.match_faces(req, student)

        assert "Caller lacks BIOMETRIC_MATCHING_EXECUTE permission" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_direct_service_call_fails_closed_when_matching_disabled(self) -> None:
        """An authorized investigator still CANNOT execute matching when feature is disabled."""
        settings = _make_unit_settings(BIOMETRIC_MATCHING_ENABLED=False)
        mock_session = AsyncMock()
        service = FaceMatchingService.from_session(mock_session, settings=settings)

        investigator = _create_principal(role_code=RoleCode.INVESTIGATOR.value)
        req = FaceMatchRequest(
            governance_record_id=uuid4(),
            probe_image_base64=base64.b64encode(_create_test_png()).decode(),
            reference_id=uuid4(),
        )

        with pytest.raises(BiometricsDisabledError) as exc_info:
            await service.match_faces(req, investigator)

        assert "Biometric face matching is strictly disabled" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_super_admin_cannot_bypass_matching_disabled_invariant(self) -> None:
        """Even SUPER_ADMIN cannot bypass BIOMETRIC_MATCHING_ENABLED=False at service layer."""
        settings = _make_unit_settings(BIOMETRIC_MATCHING_ENABLED=False)
        mock_session = AsyncMock()
        service = FaceMatchingService.from_session(mock_session, settings=settings)

        super_admin = _create_principal(role_code=RoleCode.SUPER_ADMIN.value)
        req = FaceMatchRequest(
            governance_record_id=uuid4(),
            probe_image_base64=base64.b64encode(_create_test_png()).decode(),
            reference_id=uuid4(),
        )

        with pytest.raises(BiometricsDisabledError) as exc_info:
            await service.match_faces(req, super_admin)

        assert "Biometric face matching is strictly disabled" in str(exc_info.value)

    def test_disabled_face_matcher_fails_closed_for_both_operations(self) -> None:
        """DisabledFaceMatcherProvider must raise BiometricsDisabledError for extraction and matching."""
        matcher = DisabledFaceMatcherProvider()
        test_png = _create_test_png()

        with pytest.raises(BiometricsDisabledError) as exc1:
            matcher.extract_features(test_png)
        assert "strictly disabled" in str(exc1.value)

        with pytest.raises(BiometricsDisabledError) as exc2:
            matcher.match_faces(MagicMock(), MagicMock())
        assert "strictly disabled" in str(exc2.value)

    def test_matcher_factory_returns_disabled_provider_when_disabled(self) -> None:
        """When enabled=False, get_face_matcher MUST return DisabledFaceMatcherProvider regardless of provider string."""
        for provider_str in ["disabled", "mock", "local", "unknown"]:
            matcher = get_face_matcher(enabled=False, provider=provider_str)
            assert isinstance(matcher, DisabledFaceMatcherProvider)


# ===========================================================================
# Group D: Separation of Capabilities & Prohibited Purposes
# ===========================================================================


class TestPhase72SeparationOfCapabilities:
    """Verify that detection is decoupled from matching, and prohibited uses fail closed."""

    @pytest.mark.asyncio
    async def test_face_detection_does_not_extract_features_or_templates(self) -> None:
        """Face detection extracts coordinates only; zero feature vectors or templates."""
        settings = _make_unit_settings(
            BIOMETRIC_ANALYSIS_ENABLED=True,
            BIOMETRIC_DETECTION_ENABLED=True,
            BIOMETRIC_PROVIDER="mock",
        )
        mock_session = AsyncMock()
        service = FaceDetectionService(mock_session, settings=settings)

        # Mock approved governance record
        gov_record = BiometricGovernanceRecord(
            id=uuid4(),
            tenant_id=uuid4(),
            department_id=uuid4(),
            purpose=BiometricPurpose.PRIVACY_REDACTION_BLURRING.value,
            lawful_basis="statutory_legal_obligation",
            status="approved",
            consent_status="active",
        )
        service.governance_repo.get_by_id = AsyncMock(return_value=gov_record)

        investigator = _create_principal(
            role_code=RoleCode.INVESTIGATOR.value,
            department_id=gov_record.department_id,
        )
        test_png = _create_test_png()

        response = await service.detect_faces(test_png, gov_record.id, investigator)

        # Verify only bounding boxes and count are returned
        assert response.face_count >= 1
        for face in response.detected_faces:
            assert hasattr(face, "bounding_box")
            assert len(face.bounding_box) == 4
            assert hasattr(face, "confidence")
            assert hasattr(face, "landmarks")
            # Invariant: NO feature vectors, embeddings, or templates are present
            assert not hasattr(face, "feature_vector")
            assert not hasattr(face, "template")
            assert not hasattr(face, "embedding")

    def test_prohibited_purposes_rejected_by_validator(self) -> None:
        """Every defined prohibited biometric purpose must raise ValueError in validator."""
        for prohibited in ProhibitedBiometricPurpose:
            with pytest.raises(ValueError) as exc_info:
                validate_biometric_purpose(prohibited.value)
            assert "strictly forbidden by policy" in str(exc_info.value)

    def test_prohibited_purposes_frozenset_integrity(self) -> None:
        """Verify the exact membership of PROHIBITED_BIOMETRIC_PURPOSES."""
        expected = {
            "mass_surveillance_crowd_scanning",
            "autonomous_punitive_decision",
            "emotion_or_sentiment_inference",
            "demographic_profiling",
            "covert_unauthorized_tracking",
        }
        assert PROHIBITED_BIOMETRIC_PURPOSES == expected


# ===========================================================================
# Group E: Route Introspection & 1:N Search Absence Audit
# ===========================================================================


class TestPhase72RouteIntrospection:
    """Verify API router structure to ensure absence of any 1:N surveillance endpoints."""

    def test_no_1_to_n_search_routes_exist_in_router(self) -> None:
        """Inspect all biometrics routes to confirm zero 1:N search or gallery endpoints."""
        from backend.app.api.v1.biometrics import router

        registered_paths = [route.path for route in router.routes]

        # Verify prohibited 1:N route patterns do not exist
        for path in registered_paths:
            path_lower = path.lower()
            assert "search" not in path_lower, f"Forbidden 1:N route found: {path}"
            assert "identify" not in path_lower, f"Forbidden 1:N route found: {path}"
            assert "crowd" not in path_lower, f"Forbidden 1:N route found: {path}"
            assert "gallery" not in path_lower, f"Forbidden 1:N route found: {path}"

        # Confirm only pairwise /match exists for matching
        match_routes = [r for r in router.routes if "match" in r.path]
        assert len(match_routes) == 1
        assert match_routes[0].path == "/biometrics/match"


# ===========================================================================
# Group F: API Authorization Dependencies (401 / 403 Enforcement)
# ===========================================================================


class TestPhase72ApiAuthorizationDependencies:
    """Verify endpoint-level security dependencies reject unauthenticated and unauthorized callers."""

    @pytest.mark.asyncio
    async def test_unauthenticated_request_raises_authentication_error(self) -> None:
        """Requests without bearer credentials fail with UNAUTHENTICATED error."""
        with pytest.raises(AuthenticationError) as exc_info:
            await get_current_principal(auth_service=AsyncMock(), credentials=None)
        assert exc_info.value.code == "UNAUTHENTICATED"
        assert "Authentication credentials were not provided" in str(exc_info.value)

    def test_permission_dependency_rejects_student_role(self) -> None:
        """require_permission rejects STUDENT role for BIOMETRIC_MATCHING_EXECUTE."""
        dep = require_permission(Permission.BIOMETRIC_MATCHING_EXECUTE)
        student = _create_principal(role_code=RoleCode.STUDENT.value)

        with pytest.raises(PermissionDeniedError) as exc_info:
            dep(student)

        assert exc_info.value.code == "PERMISSION_DENIED"
        assert "ROLE_STUDENT" in str(exc_info.value)
        assert "biometric:matching:execute" in str(exc_info.value)

    def test_permission_dependency_allows_authorized_investigator(self) -> None:
        """require_permission passes for INVESTIGATOR possessing BIOMETRIC_MATCHING_EXECUTE."""
        dep = require_permission(Permission.BIOMETRIC_MATCHING_EXECUTE)
        investigator = _create_principal(role_code=RoleCode.INVESTIGATOR.value)

        resolved_user = dep(investigator)
        assert resolved_user.user_id == investigator.user_id

    def test_permission_denial_message_clarity(self) -> None:
        """Permission denial error message clearly indicates role and required permission."""
        dep = require_permission(Permission.BIOMETRIC_CONFIG_MANAGE)
        investigator = _create_principal(role_code=RoleCode.INVESTIGATOR.value)

        with pytest.raises(PermissionDeniedError) as exc_info:
            dep(investigator)

        assert "ROLE_INVESTIGATOR" in str(exc_info.value)
        assert "biometric:config:manage" in str(exc_info.value)


# ===========================================================================
# Group G: Cross-Subsystem Violence Detection Isolation
# ===========================================================================


class TestPhase72CrossSubsystemIsolation:
    """Verify violence detection and biometric matching subsystems remain strictly decoupled."""

    def test_violence_detection_does_not_import_biometric_matching(self) -> None:
        """The violence detection module must not depend on face matching or biometrics services."""
        import sys

        import ai_services.violence_detection.classifier as v_classifier
        import ai_services.violence_detection.evaluation as v_eval

        with open(v_classifier.__file__, encoding="utf-8") as f:
            classifier_src = f.read()
        with open(v_eval.__file__, encoding="utf-8") as f:
            eval_src = f.read()

        for forbidden in [
            "ai_services.face_matching",
            "backend.app.services.biometrics",
            "DisabledFaceMatcherProvider",
            "FaceMatchingService",
        ]:
            assert forbidden not in classifier_src, f"Leaked import '{forbidden}' in classifier.py"
            assert forbidden not in eval_src, f"Leaked import '{forbidden}' in evaluation.py"


# ===========================================================================
# Group H: Data Protection & Zero Template Leakage
# ===========================================================================


class TestPhase72DataProtectionGuards:
    """Verify that read models and responses never expose raw feature templates."""

    def test_reference_read_schema_omits_raw_template_payload(self) -> None:
        """BiometricReferenceRead schema only includes digest, never encrypted or raw templates."""
        from backend.app.schemas.biometrics import BiometricReferenceRead

        field_names = set(BiometricReferenceRead.model_fields.keys())
        assert "template_digest" in field_names
        assert "encrypted_template" not in field_names
        assert "raw_template" not in field_names
        assert "feature_vector" not in field_names
        assert "embedding" not in field_names

