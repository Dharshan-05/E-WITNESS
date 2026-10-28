"""Unit API tests for Phase 77 quality review workflow endpoints."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_services.face_detection.review import (
    HumanReviewDetermination,
    QualityReviewStatus,
    UnifiedReviewDecision,
)
from backend.app.config.settings import Settings
from backend.app.core.authorization import RoleCode
from backend.app.core.biometrics import BIOMETRIC_ADVISORY_DISCLAIMER
from backend.app.main import create_app
from backend.app.models.biometrics import BiometricQualityReview
from backend.app.repositories.biometrics import BiometricQualityReviewRepository
from backend.app.schemas.auth import AuthenticatedPrincipal
from backend.app.services.biometrics import QualityReviewWorkflowService


def _get_test_settings() -> Settings:
    return Settings(
        ENVIRONMENT="testing",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/15",
        STORAGE_ENDPOINT_URL="https://s3.test.internal:9000",
        STORAGE_BUCKET_NAME="test-bucket",
        STORAGE_ACCESS_KEY="test_access_key_valid",
        STORAGE_SECRET_KEY="test_secret_key_valid",
        AUTH_SECRET_KEY="test_key_with_length_greater_than_32_characters",
        AI_API_KEY="test",
        BIOMETRIC_ANALYSIS_ENABLED=True,
        BIOMETRIC_DETECTION_ENABLED=True,
        BIOMETRIC_MATCHING_ENABLED=False,
    )


@pytest.mark.asyncio
async def test_api_review_lifecycle_endpoints() -> None:
    """Test API routes /faces/reviews end-to-end using dependency overrides."""
    settings = _get_test_settings()
    app = create_app(settings)

    reviews_db: dict[UUID, BiometricQualityReview] = {}
    dept_id = uuid4()
    investigator_id = uuid4()

    mock_repo = MagicMock(spec=BiometricQualityReviewRepository)

    async def mock_create(review: BiometricQualityReview) -> BiometricQualityReview:
        reviews_db[review.id] = review
        return review

    async def mock_get(review_id: UUID, *, department_id: UUID | None = None) -> BiometricQualityReview | None:
        rec = reviews_db.get(review_id)
        if rec and (department_id is None or rec.department_id == department_id):
            return rec
        return None

    async def mock_list(*, department_id: UUID | None = None, status: str | None = None, **kwargs) -> list[BiometricQualityReview]:
        return [r for r in reviews_db.values() if (department_id is None or r.department_id == department_id) and (status is None or r.status == status)]

    async def mock_count(*, department_id: UUID | None = None, status: str | None = None, **kwargs) -> int:
        return len(await mock_list(department_id=department_id, status=status))

    mock_repo.create = AsyncMock(side_effect=mock_create)
    mock_repo.get_by_id = AsyncMock(side_effect=mock_get)
    mock_repo.list_for_department = AsyncMock(side_effect=mock_list)
    mock_repo.count_for_department = AsyncMock(side_effect=mock_count)

    mock_service = QualityReviewWorkflowService(review_repo=mock_repo)

    # Mock user dependency
    investigator_principal = AuthenticatedPrincipal(
        user_id=investigator_id,
        email="inv@ewitness.edu",
        full_name="Investigator User",
        account_status="active",
        is_active=True,
        role_code=RoleCode.INVESTIGATOR.value,
        department_id=dept_id,
        session_id=uuid4(),
    )

    from backend.app.api.dependencies import (
        get_current_principal,
        get_quality_review_workflow_service,
    )

    app.dependency_overrides[get_quality_review_workflow_service] = lambda: mock_service
    app.dependency_overrides[get_current_principal] = lambda: investigator_principal

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver.local") as client:
        # 1. POST /api/v1/biometrics/faces/reviews
        resp_create = await client.post(
            "/api/v1/biometrics/faces/reviews",
            json={
                "detected_faces_count": 1,
                "redacted_faces_count": 1,
                "quality_result": {"requires_human_review": False},
                "geometry_result": {"is_valid": True},
            },
        )
        assert resp_create.status_code == 201, resp_create.text
        data_create = resp_create.json()
        review_id = data_create["id"]
        assert data_create["status"] == "PENDING_REVIEW"
        assert data_create["unified_decision"] == "READY_FOR_HUMAN_REVIEW"
        assert "NOT establish identity" in data_create["disclaimer"]

        # 2. GET /api/v1/biometrics/faces/reviews
        resp_list = await client.get("/api/v1/biometrics/faces/reviews")
        assert resp_list.status_code == 200
        assert resp_list.json()["total"] == 1

        # 3. GET /api/v1/biometrics/faces/reviews/{review_id}
        resp_get = await client.get(f"/api/v1/biometrics/faces/reviews/{review_id}")
        assert resp_get.status_code == 200
        assert resp_get.json()["id"] == review_id

        # 4. POST /api/v1/biometrics/faces/reviews/{review_id}/assign
        resp_assign = await client.post(
            f"/api/v1/biometrics/faces/reviews/{review_id}/assign",
            json={"reviewer_id": str(investigator_id)},
        )
        assert resp_assign.status_code == 200
        assert resp_assign.json()["status"] == "IN_REVIEW"
        assert resp_assign.json()["assigned_reviewer_id"] == str(investigator_id)

        # 5. POST /api/v1/biometrics/faces/reviews/{review_id}/verdict (approved)
        resp_verdict = await client.post(
            f"/api/v1/biometrics/faces/reviews/{review_id}/verdict",
            json={
                "determination": "approved",
                "notes": "Redaction verified complete.",
            },
        )
        assert resp_verdict.status_code == 200
        assert resp_verdict.json()["status"] == "COMPLETED"
        assert resp_verdict.json()["unified_decision"] == "REVIEW_COMPLETED"
        assert resp_verdict.json()["human_determination"] == "approved"
