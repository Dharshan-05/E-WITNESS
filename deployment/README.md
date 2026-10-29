# E-WITNESS — Production Deployment & Infrastructure Hardening Guide (Phase 117)

**Document ID:** `EW-DOC-OPS-117`  
**Phase:** Phase 117 — Production Deployment and Infrastructure Hardening  
**Audience:** DevSecOps Engineers, Infrastructure Architects, SREs, Security Officers  
**Current Production Readiness Status:** **NO-GO** (Pending Institutional Deployment Authorization)

---

## 1. Architectural Overview & Trust Boundaries

E-WITNESS deployment architecture separates internet-facing ingress, stateless application compute, isolated migration jobs, and stateful backing infrastructure across segmented network tiers:

```
[ Internet / Institutional Clients ]
                 │ (HTTPS :443 / TLS 1.3 Strict)
                 ▼
     ┌───────────────────────┐
     │  Hardened Ingress      │ Nginx 1.27 (TLS termination, HSTS, CSP,
     │  Reverse Proxy        │ strict auth rate limiting, non-root)
     └───────────┬───────────┘
                 │ (Internal HTTP keepalive)
                 ▼
     ┌───────────────────────┐      ┌─────────────────────────┐
     │  Backend Web Workers  │◄─────┤ Migration Runner (Job)  │
     │  FastAPI / Uvicorn    │      │ deploy_migrations.py    │
     │  UID 10001:10001      │      │ Runs before web workers │
     └───────────┬───────────┘      └────────────┬────────────┘
                 │                               │
                 ├───────────────────────────────┤
                 │ (Mutual TLS / Encrypted internal network)
                 ▼                               ▼
       ┌───────────────────┐           ┌───────────────────┐
       │   PostgreSQL 16   │           │   Redis 7 (TLS)   │
       │   Relational Store│           │   rediss://       │
       └───────────────────┘           └───────────────────┘
                 │
                 ▼
       ┌───────────────────┐
       │  S3 Object Store  │
       │  https:// (TLS)   │
       └───────────────────┘
```

---

## 2. Hardened Container Specification

The container image defined in [`deployment/Dockerfile`](file:///d:/PROJECT/E-WITTNESS/deployment/Dockerfile) enforces multi-tier defense-in-depth:

1. **Multi-Stage Build Isolation**:
   - Stage 1 (`builder`): Compiles wheel dependencies with `build-essential` and `libpq-dev`.
   - Stage 2 (`runtime`): Uses a minimal Debian base (`python:3.13-slim-bookworm`). Zero compilers, development headers, or build tools are present in the runtime image.
2. **Minimal Non-Root Execution**:
   - Runs strictly under unprivileged user `appuser` (`UID 10001`, `GID 10001`) with login disabled (`/sbin/nologin`).
   - Read-only code permissions: `chmod -R 550 /app`.
3. **Signal Forwarding & Zombie Reaping**:
   - `tini` is installed as the PID 1 init process (`/usr/bin/tini -- python -m uvicorn ...`).
   - Ensures `SIGTERM` signals from container orchestrators (Docker, Kubernetes) are propagated immediately to Uvicorn for graceful shutdown.
4. **Zero-Dependency Health Checks**:
   - Uses the Python standard library (`urllib.request`) targeting `/api/v1/health/live`.
   - Eliminates vulnerabilities associated with `curl` or `wget` binaries in production containers.
5. **Runtime Resource Bounds**:
   - All production containers enforce CPU and memory limits (`limits.cpus: "4.0"`, `limits.memory: 4096M`).
   - Root filesystem is mounted read-only (`read_only: true`), with an isolated in-memory scratch space (`tmpfs: /tmp:rw,noexec,nosuid,size=256M`).

---

## 3. Environment Separation & Configuration Precedence

E-WITNESS enforces a strict firewall between development and production configurations:

| Parameter | Development / Local (`docker-compose.yml`) | Production (`docker-compose.prod.yml`) |
| :--- | :--- | :--- |
| `ENVIRONMENT` | `development` | `production` (Enforces fail-fast security gate) |
| `DEBUG` | Optional (`true`/`false`) | `false` strictly enforced |
| `DB_ECHO` | Optional (`true`/`false`) | `false` strictly enforced |
| `LOG_LEVEL` | `DEBUG` / `INFO` | `INFO` / `WARNING` / `ERROR` (`DEBUG` rejected) |
| `LOG_FORMAT` | `console` or `json` | `json` strictly enforced (structured auditing) |
| `LOG_REDACT_SENSITIVE`| Optional | `true` strictly enforced |
| `DATABASE_URL` | Local PostgreSQL or SQLite | Remote `postgresql+asyncpg://` with strong credentials |
| `REDIS_URL` | Local `redis://` allowed | Encrypted `rediss://` TLS transport mandatory |
| `STORAGE_ENDPOINT_URL`| Local HTTP MinIO allowed | Remote `https://` TLS endpoint mandatory |
| `CORS_ALLOWED_ORIGINS`| Localhost allowed | Strict HTTPS institutional domains (No `*`, no `http://`) |
| `ALLOWED_HOSTS` | Localhost allowed | Strict hostnames (No `*`, no `localhost`) |
| `OpenAPI / Docs` | Enabled at `/docs` | Automatically disabled (`openapi_url=None`) |

### Secret Injection
- **NEVER** bake credentials or `.env` files into Docker images.
- In production, inject secrets via environment variables from an approved secrets manager (AWS Secrets Manager, Azure Key Vault, HashiCorp Vault, or Kubernetes `Secret` mounts).
- Use [`.env.production.example`](file:///d:/PROJECT/E-WITTNESS/.env.production.example) as the reference schema for required environment variables.

---

## 4. Controlled Database Migration Step

Database migrations must **NEVER** run automatically inside general web worker startup. Running migrations during web server initialization introduces race conditions in multi-replica deployments and risks partial migrations during scaling events.

### Dedicated Migration Runner
E-WITNESS provides [`scripts/deploy_migrations.py`](file:///d:/PROJECT/E-WITTNESS/scripts/deploy_migrations.py) to execute migrations as an explicit, controlled gate in deployment pipelines:

```bash
# 1. Pre-flight drift and readiness verification (Check mode, returns 0 if up-to-date, 2 if pending/drift)
python scripts/deploy_migrations.py --check --timeout 30

# 2. Apply forward migrations to head
python scripts/deploy_migrations.py --revision head --timeout 45

# 3. Rollback / downgrade (if rollback testing or incident remediation is required)
python scripts/deploy_migrations.py --downgrade <revision_id>
```

In [`deployment/docker-compose.prod.yml`](file:///d:/PROJECT/E-WITTNESS/deployment/docker-compose.prod.yml), the `migration-runner` one-off service executes to completion before the `backend` web service is permitted to start:

```yaml
backend:
  depends_on:
    migration-runner:
      condition: service_completed_successfully
```

---

## 5. Health & Readiness Telemetry (SEC-008)

The application provides isolated liveness and readiness endpoints:

- **Liveness Probe** (`GET /api/v1/health/live` or `GET /health`):
  - Returns `{"status": "ok", "service": "E-WITNESS", "version": "0.1.0", "environment": "production"}`.
  - Confirms process event loop responsiveness without touching downstream databases or caches.
- **Readiness Probe** (`GET /api/v1/health/ready`):
  - Actively probes PostgreSQL (`SELECT 1`), Redis (`PING`), and S3 storage connectivity with bounded timeouts.
  - Returns HTTP 200 when ready, HTTP 503 when degraded.
  - **Zero Credential Disclosure**: Status outputs categorize dependencies strictly as `ready`, `not_checked`, or `unavailable`. No hostnames, passwords, connection URIs, or internal network topology are leaked.

---

## 6. Backup, Disaster Recovery & Restoration Runbook

### Backup Prerequisites & Automation
1. **PostgreSQL Snapshots**:
   - Automated continuous archiving via WAL archiving and daily `pg_dump` binary archives.
   - Cryptographic hashing (`SHA-256`) of backup archives before uploading to offsite encrypted storage.
   - Use [`scripts/disaster_recovery.py`](file:///d:/PROJECT/E-WITTNESS/scripts/disaster_recovery.py) to verify evidence ledger consistency, audit trails, and legal hold preservation.
2. **Object Storage Replication**:
   - Cross-region replication enabled on `STORAGE_BUCKET_NAME` with object versioning and object-lock legal holds.
3. **Recovery Objectives**:
   - **RPO (Recovery Point Objective)**: $\le 15\text{ minutes}$.
   - **RTO (Recovery Time Objective)**: $\le 30\text{ minutes}$.

### Restoration Procedure
1. Provision a target database or restore into an isolated verification schema (`dr_verification_restore`).
2. Restore database schema and data from the latest encrypted backup archive:
   ```bash
   pg_restore -h <db_host> -U <db_user> -d <db_name> --clean --if-exists <backup_file.dump>
   ```
3. Run Alembic migration verification to ensure schema alignment:
   ```bash
   python scripts/deploy_migrations.py --check
   ```
4. Execute [`scripts/disaster_recovery.py`](file:///d:/PROJECT/E-WITTNESS/scripts/disaster_recovery.py) to validate cryptographic hashes of evidence attachments and audit event logs.

---

## 7. Rollback & Incident Response Procedures

If a deployment fails health checks or introduces regression:

1. **Traffic Diversion**:
   - Ingress reverse proxy immediately routes traffic back to the previous stable blue/green release pool.
2. **Container Image Rollback**:
   - Revert container image tag to the last approved SHA in the deployment manifest.
3. **Database Schema Rollback**:
   - If the migration introduced breaking schema changes, execute the rollback script to revert down to the target revision:
     ```bash
     python scripts/deploy_migrations.py --downgrade <previous_revision_id>
     ```
   - *Note*: Downward migrations must only be performed if data compatibility has been verified. Non-destructive migrations (expand-contract pattern) are standard for E-WITNESS.

---

## 8. Strict Safety Invariants & Governance

- **Biometric Matching Ban**: `BIOMETRIC_MATCHING_ENABLED = False` permanently across all configurations. Automated biometric face matching, identity recognition, or profiling is prohibited by architectural decree.
- **AI Non-Authoritative Advisory Boundary**: AI analysis components are strictly advisory. AI cannot make binding case determinations, sign off on evidence, or alter workflow states without human reviewer action.
- **Backend Authorization Authority**: All authorization, tenant boundaries, role verification, and audit logging are enforced authoritatively on the backend.
- **Readiness Gate**: Production readiness remains **NO-GO** until explicit institutional authorization, SOC 2 / HIPAA compliance audits, and legal counsel sign-off are completed.
