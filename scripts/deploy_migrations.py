"""Controlled Database Migration & Schema Pre-Flight Deployment CLI (Phase 117).

Provides a secure, deterministic migration runner for CI/CD and deployment pipelines.

Security & Architectural Guarantees:
- Runs as an independent, isolated deployment phase (NEVER on web worker startup).
- Validates database target isolation and connection health prior to migration execution.
- Emits structured, credential-redacted status logs (SEC-008).
- Verifies migration head consistency and detects uncommitted schema drift (--check).
- Returns distinct shell exit codes for CI/CD gate automation:
    0: Success / Fully up-to-date
    1: Fatal error / Connection failure / Unhandled migration exception
    2: Migration pending or schema drift detected (in --check mode)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config.settings import Settings, get_settings  # noqa: E402
from backend.app.core.logging import configure_logging, get_logger  # noqa: E402
from backend.app.core.secrets import redact_text, redact_url  # noqa: E402
from backend.app.infrastructure.database import (  # noqa: E402
    create_db_engine,
    validate_database_target_isolation,
    verify_database_connectivity,
)
from backend.app.infrastructure.migrations import (  # noqa: E402
    detect_schema_drift,
    get_current_database_revision,
    get_expected_head_revision,
    run_migrations_downgrade,
    run_migrations_upgrade,
)

logger = get_logger("deployment.migrations")


async def execute_migration_pipeline(
    settings: Settings,
    *,
    check_only: bool = False,
    target_revision: str = "head",
    downgrade_revision: str | None = None,
    timeout_seconds: float = 30.0,
) -> int:
    """Execute pre-flight check and controlled migration or drift verification."""
    configure_logging(settings)
    redacted_db_url = redact_url(settings.DATABASE_URL)

    logger.info(
        "Initiating controlled deployment migration step",
        extra={
            "environment": str(settings.ENVIRONMENT),
            "target_database": redacted_db_url,
            "check_only": check_only,
            "target_revision": target_revision if not downgrade_revision else f"downgrade->{downgrade_revision}",
        },
    )

    # 1. Isolation check
    try:
        validate_database_target_isolation(settings)
    except Exception as exc:
        logger.error(
            "Database isolation guard failure",
            extra={"error": redact_text(str(exc))},
        )
        return 1

    engine = create_db_engine(settings)
    try:
        # 2. Pre-flight connectivity check
        start_time = time.perf_counter()
        logger.info(f"Verifying database connectivity (timeout={timeout_seconds}s)...")
        is_connected = await verify_database_connectivity(engine, timeout_seconds=timeout_seconds)
        if not is_connected:
            logger.error(
                "Database connectivity pre-flight check FAILED: Database unreachable",
                extra={"target_url": redacted_db_url},
            )
            return 1

        elapsed = time.perf_counter() - start_time
        logger.info(f"Database connectivity confirmed in {elapsed:.3f}s")

        # 3. Check current vs expected revisions
        current_rev = await get_current_database_revision(engine)
        expected_head = get_expected_head_revision()
        logger.info(
            "Retrieved migration revisions",
            extra={"current_applied": current_rev or "None", "expected_head": expected_head or "None"},
        )

        if check_only:
            # Check mode: detect if current == expected head and check drift
            is_up_to_date = (current_rev == expected_head) and (expected_head is not None)
            drift = await detect_schema_drift(engine)

            if not is_up_to_date:
                logger.warning(
                    "Database schema is NOT at migration head",
                    extra={"current_applied": current_rev, "expected_head": expected_head},
                )
                return 2

            if drift:
                logger.warning(
                    f"Detected {len(drift)} schema diff(s) between live DB and Base.metadata",
                    extra={"drift_count": len(drift)},
                )
                return 2

            logger.info("Database schema is fully up-to-date with zero drift")
            return 0

        # 4. Perform upgrade or downgrade
        if downgrade_revision is not None:
            logger.warning(
                f"Executing database DOWNGRADE to revision: {downgrade_revision}",
                extra={"target_revision": downgrade_revision},
            )
            await run_migrations_downgrade(engine, revision=downgrade_revision)
            new_rev = await get_current_database_revision(engine)
            logger.info(f"Database successfully downgraded to revision: {new_rev}")
            return 0

        logger.info(f"Applying database migrations forward to revision: {target_revision}")
        await run_migrations_upgrade(engine, revision=target_revision)
        new_rev = await get_current_database_revision(engine)
        logger.info(
            "Database migrations applied successfully",
            extra={"applied_revision": new_rev, "expected_head": expected_head},
        )
        return 0

    except Exception as exc:
        safe_error = redact_text(str(exc))
        logger.error(
            "Database migration execution failed",
            extra={"error": safe_error},
        )
        return 1
    finally:
        await engine.dispose()


def main() -> None:
    """CLI entrypoint for deploy_migrations."""
    parser = argparse.ArgumentParser(
        description="E-WITNESS Controlled Database Migration Runner (Phase 117)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the database is at migration head without applying changes",
    )
    parser.add_argument(
        "--revision",
        default="head",
        help="Target migration revision to upgrade to (default: 'head')",
    )
    parser.add_argument(
        "--downgrade",
        default=None,
        help="Revert database migrations down to specified revision (e.g. 'base' or revision ID)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Database pre-flight connection timeout in seconds (default: 30.0)",
    )

    args = parser.parse_args()

    try:
        settings = get_settings()
    except Exception as exc:
        safe_msg = redact_text(str(exc))
        print(f"[FATAL] Failed to load or validate application settings: {safe_msg}", file=sys.stderr)
        sys.exit(1)

    exit_code = asyncio.run(
        execute_migration_pipeline(
            settings=settings,
            check_only=args.check,
            target_revision=args.revision,
            downgrade_revision=args.downgrade,
            timeout_seconds=args.timeout,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
