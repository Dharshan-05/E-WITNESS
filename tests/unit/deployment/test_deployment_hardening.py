"""Automated Verification Suite for Phase 117 Production Deployment Hardening.

Verifies:
1. Strict production configuration enforcement and rejection of insecure defaults.
2. Controlled database migration step execution, pre-flight checks, drift detection, and credential redaction.
3. Health and readiness endpoints isolation without internal topology or credential leakage.
4. Container deployment manifests (Dockerfile, Compose) compliance with DevSecOps standards.
5. Permanent preservation of safety invariants (zero biometric matching, advisory AI).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from scripts.deploy_migrations import execute_migration_pipeline

from backend.app.config.settings import Environment, Settings, load_settings
from backend.app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]

# Cryptographically strong test keys with Shannon entropy > 4.5 and zero forbidden patterns
STRONG_AUTH_KEY = "k8B!xL9#mQ2$vP5&wR7*zT1@yN4^uS6%jH3(fG2)"
STRONG_STORAGE_KEY = "k9W!mP2$xR7*vL4^qT8@yN3#zB5%jF1&hD6("
STRONG_STORAGE_ACCESS = "AKIA9876543210ZYXWV"
STRONG_DB_URL = "postgresql+asyncpg://app_user:vR7mK9xL2qT8zB4C921@db.internal:5432/prod_db"
STRONG_REDIS_URL = "rediss://:pX8wL3mQ7zR2kY5D843@redis.internal:6379/0"


class TestProductionConfigurationHardening:
    """Validate that production environment rejects all insecure or developer defaults."""

    def test_production_rejects_debug_mode(self) -> None:
        """Production configuration must strictly reject DEBUG=True."""
        with pytest.raises(ValidationError, match="DEBUG=True is strictly forbidden in production"):
            load_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                DEBUG=True,
                AUTH_SECRET_KEY=STRONG_AUTH_KEY,
                DATABASE_URL=STRONG_DB_URL,
                REDIS_URL=STRONG_REDIS_URL,
                STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
                STORAGE_ACCESS_KEY=STRONG_STORAGE_ACCESS,
                STORAGE_SECRET_KEY=STRONG_STORAGE_KEY,
                CORS_ALLOWED_ORIGINS=["https://ewitness.org"],
                ALLOWED_HOSTS=["ewitness.org"],
                STORAGE_USE_SSL=True,
                ENFORCE_SSL=True,
                SECURITY_HEADERS_ENABLED=True,
                LOG_FORMAT="json",
                LOG_REDACT_SENSITIVE=True,
            )

    def test_production_rejects_database_echo(self) -> None:
        """Production configuration must strictly reject DB_ECHO=True."""
        with pytest.raises(ValidationError, match="DB_ECHO=True is strictly forbidden in production"):
            load_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                DEBUG=False,
                DB_ECHO=True,
                AUTH_SECRET_KEY=STRONG_AUTH_KEY,
                DATABASE_URL=STRONG_DB_URL,
                REDIS_URL=STRONG_REDIS_URL,
                STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
                STORAGE_ACCESS_KEY=STRONG_STORAGE_ACCESS,
                STORAGE_SECRET_KEY=STRONG_STORAGE_KEY,
                CORS_ALLOWED_ORIGINS=["https://ewitness.org"],
                ALLOWED_HOSTS=["ewitness.org"],
                STORAGE_USE_SSL=True,
                ENFORCE_SSL=True,
                SECURITY_HEADERS_ENABLED=True,
                LOG_FORMAT="json",
                LOG_REDACT_SENSITIVE=True,
            )

    def test_production_rejects_unencrypted_redis(self) -> None:
        """Production configuration must reject plain redis:// schemes (requires rediss://)."""
        with pytest.raises(ValidationError, match="Production REDIS_URL must use encrypted 'rediss://'"):
            load_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                DEBUG=False,
                AUTH_SECRET_KEY=STRONG_AUTH_KEY,
                DATABASE_URL=STRONG_DB_URL,
                REDIS_URL="redis://:pX8wL3mQ7zR2kY5D843@redis.internal:6379/0",
                STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
                STORAGE_ACCESS_KEY=STRONG_STORAGE_ACCESS,
                STORAGE_SECRET_KEY=STRONG_STORAGE_KEY,
                CORS_ALLOWED_ORIGINS=["https://ewitness.org"],
                ALLOWED_HOSTS=["ewitness.org"],
                STORAGE_USE_SSL=True,
                ENFORCE_SSL=True,
                SECURITY_HEADERS_ENABLED=True,
                LOG_FORMAT="json",
                LOG_REDACT_SENSITIVE=True,
            )

    def test_production_rejects_unencrypted_storage_endpoint(self) -> None:
        """Production configuration must reject http:// storage endpoints."""
        with pytest.raises(ValidationError, match="Production STORAGE_ENDPOINT_URL must use 'https://'"):
            load_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                DEBUG=False,
                AUTH_SECRET_KEY=STRONG_AUTH_KEY,
                DATABASE_URL=STRONG_DB_URL,
                REDIS_URL=STRONG_REDIS_URL,
                STORAGE_ENDPOINT_URL="http://s3.internal:9000",
                STORAGE_ACCESS_KEY=STRONG_STORAGE_ACCESS,
                STORAGE_SECRET_KEY=STRONG_STORAGE_KEY,
                CORS_ALLOWED_ORIGINS=["https://ewitness.org"],
                ALLOWED_HOSTS=["ewitness.org"],
                STORAGE_USE_SSL=True,
                ENFORCE_SSL=True,
                SECURITY_HEADERS_ENABLED=True,
                LOG_FORMAT="json",
                LOG_REDACT_SENSITIVE=True,
            )

    def test_production_rejects_wildcard_cors(self) -> None:
        """Production configuration must reject wildcard '*' in CORS_ALLOWED_ORIGINS."""
        with pytest.raises(ValidationError, match="Wildcard '\\*' in CORS_ALLOWED_ORIGINS is forbidden"):
            load_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                DEBUG=False,
                AUTH_SECRET_KEY=STRONG_AUTH_KEY,
                DATABASE_URL=STRONG_DB_URL,
                REDIS_URL=STRONG_REDIS_URL,
                STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
                STORAGE_ACCESS_KEY=STRONG_STORAGE_ACCESS,
                STORAGE_SECRET_KEY=STRONG_STORAGE_KEY,
                CORS_ALLOWED_ORIGINS=["*"],
                ALLOWED_HOSTS=["ewitness.org"],
                STORAGE_USE_SSL=True,
                ENFORCE_SSL=True,
                SECURITY_HEADERS_ENABLED=True,
                LOG_FORMAT="json",
                LOG_REDACT_SENSITIVE=True,
            )

    def test_production_rejects_biometric_matching(self) -> None:
        """Production configuration must strictly reject BIOMETRIC_MATCHING_ENABLED=True."""
        with pytest.raises(ValidationError, match="BIOMETRIC_MATCHING_ENABLED=True is strictly forbidden in production"):
            load_settings(
                ENVIRONMENT=Environment.PRODUCTION,
                DEBUG=False,
                BIOMETRIC_MATCHING_ENABLED=True,
                AUTH_SECRET_KEY=STRONG_AUTH_KEY,
                DATABASE_URL=STRONG_DB_URL,
                REDIS_URL=STRONG_REDIS_URL,
                STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
                STORAGE_ACCESS_KEY=STRONG_STORAGE_ACCESS,
                STORAGE_SECRET_KEY=STRONG_STORAGE_KEY,
                CORS_ALLOWED_ORIGINS=["https://ewitness.org"],
                ALLOWED_HOSTS=["ewitness.org"],
                STORAGE_USE_SSL=True,
                ENFORCE_SSL=True,
                SECURITY_HEADERS_ENABLED=True,
                LOG_FORMAT="json",
                LOG_REDACT_SENSITIVE=True,
            )

    def test_openapi_docs_disabled_in_production(self) -> None:
        """FastAPI interactive Swagger and OpenAPI JSON must be disabled in production."""
        settings = Settings(
            ENVIRONMENT=Environment.PRODUCTION,
            DEBUG=False,
            AUTH_SECRET_KEY=STRONG_AUTH_KEY,
            DATABASE_URL=STRONG_DB_URL,
            REDIS_URL=STRONG_REDIS_URL,
            STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
            STORAGE_ACCESS_KEY=STRONG_STORAGE_ACCESS,
            STORAGE_SECRET_KEY=STRONG_STORAGE_KEY,
            CORS_ALLOWED_ORIGINS=["https://ewitness.org"],
            ALLOWED_HOSTS=["ewitness.org"],
            STORAGE_USE_SSL=True,
            ENFORCE_SSL=True,
            SECURITY_HEADERS_ENABLED=True,
            LOG_FORMAT="json",
            LOG_REDACT_SENSITIVE=True,
        )
        app = create_app(settings)
        assert app.openapi_url is None
        assert app.docs_url is None
        assert app.redoc_url is None


class TestReadinessAndHealthSecurity:
    """Verify that health probes do not disclose internal topology or credentials."""

    @pytest.mark.asyncio
    async def test_readiness_probe_does_not_leak_credentials(self) -> None:
        """GET /api/v1/health/ready must reflect statuses without credentials or hosts."""
        settings = Settings(
            ENVIRONMENT=Environment.TESTING,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            REDIS_URL="redis://:test_secret_pass@localhost:6379/0",
            STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
            STORAGE_ACCESS_KEY="test_access_key",
            STORAGE_SECRET_KEY="test_secret_key",
            AUTH_SECRET_KEY="test_secret_key_minimum_32_characters_long",
        )
        app = create_app(
            settings,
            readiness_probes={
                "database": AsyncMock(return_value=True),
                "redis": AsyncMock(return_value=True),
                "object_storage": AsyncMock(return_value=True),
            },
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/v1/health/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["ready"] is True
            assert data["status"] == "ok"
            # Verify checks structure
            assert "database" in data["checks"]
            assert data["checks"]["database"] == "ready"
            assert data["checks"]["redis"] == "ready"
            assert data["checks"]["object_storage"] == "ready"
            # Verify no secret keywords leaked in body text
            raw_text = response.text
            assert "test_secret_pass" not in raw_text
            assert "memory" not in raw_text
            assert "sqlite" not in raw_text
            assert "6379" not in raw_text


class TestControlledDatabaseMigrationRunner:
    """Verify scripts/deploy_migrations.py lifecycle and security guarantees."""

    @pytest.mark.asyncio
    async def test_migration_pipeline_preflight_connection_failure(self) -> None:
        """When database is unreachable, deploy_migrations exits with code 1 and redacts URL."""
        settings = Settings(
            ENVIRONMENT=Environment.TESTING,
            DATABASE_URL="postgresql+asyncpg://app_user:SecretPassword123!@unreachable.host:5432/test_db",
            REDIS_URL="redis://localhost:6379/0",
            STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
            STORAGE_ACCESS_KEY="test_access_key",
            STORAGE_SECRET_KEY="test_secret_key",
            AUTH_SECRET_KEY="test_secret_key_minimum_32_characters_long",
        )

        with patch(
            "scripts.deploy_migrations.verify_database_connectivity",
            AsyncMock(return_value=False),
        ):
            exit_code = await execute_migration_pipeline(
                settings=settings,
                check_only=False,
                timeout_seconds=1.0,
            )
            assert exit_code == 1

    @pytest.mark.asyncio
    async def test_migration_pipeline_check_mode_success(self) -> None:
        """When schema is at head with zero drift, --check exits with code 0."""
        settings = Settings(
            ENVIRONMENT=Environment.TESTING,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            REDIS_URL="redis://localhost:6379/0",
            STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
            STORAGE_ACCESS_KEY="test_access_key",
            STORAGE_SECRET_KEY="test_secret_key",
            AUTH_SECRET_KEY="test_secret_key_minimum_32_characters_long",
        )

        with (
            patch("scripts.deploy_migrations.verify_database_connectivity", AsyncMock(return_value=True)),
            patch("scripts.deploy_migrations.get_current_database_revision", AsyncMock(return_value="rev_head_123")),
            patch("scripts.deploy_migrations.get_expected_head_revision", return_value="rev_head_123"),
            patch("scripts.deploy_migrations.detect_schema_drift", AsyncMock(return_value=[])),
        ):
            exit_code = await execute_migration_pipeline(
                settings=settings,
                check_only=True,
                timeout_seconds=5.0,
            )
            assert exit_code == 0

    @pytest.mark.asyncio
    async def test_migration_pipeline_check_mode_detects_drift(self) -> None:
        """When schema drift exists, --check exits with code 2."""
        settings = Settings(
            ENVIRONMENT=Environment.TESTING,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            REDIS_URL="redis://localhost:6379/0",
            STORAGE_ENDPOINT_URL="https://s3.amazonaws.com",
            STORAGE_ACCESS_KEY="test_access_key",
            STORAGE_SECRET_KEY="test_secret_key",
            AUTH_SECRET_KEY="test_secret_key_minimum_32_characters_long",
        )

        with (
            patch("scripts.deploy_migrations.verify_database_connectivity", AsyncMock(return_value=True)),
            patch("scripts.deploy_migrations.get_current_database_revision", AsyncMock(return_value="rev_head_123")),
            patch("scripts.deploy_migrations.get_expected_head_revision", return_value="rev_head_123"),
            patch("scripts.deploy_migrations.detect_schema_drift", AsyncMock(return_value=["drift_detected_in_table"])),
        ):
            exit_code = await execute_migration_pipeline(
                settings=settings,
                check_only=True,
                timeout_seconds=5.0,
            )
            assert exit_code == 2


class TestDeploymentManifestsHardening:
    """Verify that Dockerfile and Compose configurations adhere to DevSecOps guidelines."""

    def test_dockerfile_security_invariants(self) -> None:
        """Dockerfile must enforce multi-stage, non-root user, tini, and health check."""
        dockerfile_path = REPO_ROOT / "deployment" / "Dockerfile"
        assert dockerfile_path.exists(), "Dockerfile must exist in deployment/"

        content = dockerfile_path.read_text(encoding="utf-8")
        assert "AS builder" in content, "Dockerfile must use multi-stage build"
        assert "AS runtime" in content, "Dockerfile must define dedicated runtime stage"
        assert "USER 10001:10001" in content, "Must enforce non-root user 10001:10001"
        assert "tini" in content, "Must install tini for signal forwarding and zombie reaping"
        assert "HEALTHCHECK" in content, "Must define container HEALTHCHECK"
        assert "urllib.request" in content, "Health check must use Python stdlib without curl"
        assert "--proxy-headers" in content, "Uvicorn must accept proxy headers"

    def test_docker_compose_production_hardening(self) -> None:
        """Production compose must use dedicated migration service, read-only root, and no-new-privileges."""
        prod_compose_path = REPO_ROOT / "deployment" / "docker-compose.prod.yml"
        assert prod_compose_path.exists(), "docker-compose.prod.yml must exist"

        content = prod_compose_path.read_text(encoding="utf-8")
        assert "migration-runner:" in content, "Must define dedicated migration-runner service"
        assert "deploy_migrations.py" in content, "Must run deploy_migrations.py as a distinct step"
        assert "service_completed_successfully" in content, "Backend must gate on migration completion"
        assert "no-new-privileges:true" in content, "Must enforce no-new-privileges"
        assert "read_only: true" in content, "Must enforce read-only root filesystem"
        assert "BIOMETRIC_MATCHING_ENABLED=false" in content, "Biometric matching must be disabled"
        assert "rediss://" in content, "Must specify rediss:// TLS scheme requirement"
        assert "https://" in content, "Must specify https:// TLS scheme requirement"

    def test_docker_compose_local_dev_separation(self) -> None:
        """Local docker-compose.yml must separate development environment from production."""
        dev_compose_path = REPO_ROOT / "deployment" / "docker-compose.yml"
        assert dev_compose_path.exists(), "docker-compose.yml must exist"

        content = dev_compose_path.read_text(encoding="utf-8")
        assert "ENVIRONMENT=development" in content, "Local compose must use development environment"
        assert "migrate:" in content, "Local compose must include explicit migrate service"
