# BATCH 12 · PHASE 115 ACCEPTANCE REPORT
## E-WITNESS: Case Management, Dossiers & Chain-of-Custody Timeline UI

**Execution Date:** 2026-10-28  
**Project Root:** `D:\PROJECT\E-WITTNESS`  
**Frontend Directory:** `D:\PROJECT\E-WITTNESS\frontend`  
**Phase Status:** ACCEPTED WITH LIMITATIONS  
**Production Readiness:** NO-GO  

---

## 1. Executive Summary

Phase 115 implements the **Case Management, Dossiers & Chain-of-Custody Timeline UI** for the E-WITNESS digital chain-of-custody platform. This phase delivers an institutional, accessible, role-guarded investigative workspace that integrates case file management, multi-incident correlation, enriched evidence inventories, append-only case notes, and a tamper-evident chain-of-custody activity timeline.

The implementation directly aligns with the backend API contracts established in Batch 06 (Phases 56–59), Batch 09 (Phases 81–90), and Batch 11 (Phases 101–110), communicating with `/cases/...` endpoints with full optimistic concurrency locking (`expected_version_id`), separation-of-duties enforcement, and role-based action gating.

All automated verification and quality gates have passed:
- **103 Vitest tests passing** across 16 test suites (100% pass rate).
- **TypeScript strict type checking:** 0 errors (`tsc --noEmit`).
- **ESLint verification:** 0 errors / 0 warnings (`eslint .`).
- **Vite production bundle:** Clean compilation (`dist/assets/index-*.js`, gzip: 114.77 kB).
- **Backend zero-regression verification:**
  - 298 case domain, repository, and workflow unit tests passed (`tests/unit/cases/`).
  - 159 incident and evidence unit tests passed (`tests/unit/incidents/`, `tests/unit/evidence/`).

---

## 2. Implemented Capabilities & Architecture

### 2.1 Case Domain Types (`frontend/src/types/case.ts`)
- Mirrors backend Pydantic schemas in `backend/app/schemas/case.py` and domain primitives in `backend/app/core/case.py`.
- Enumerations: `CaseStatus` (`draft`, `active`, `under_review`, `closed`, `reopened`), `CasePriority` (`low`, `medium`, `high`, `critical`), `IncidentLinkType` (`primary`, `contributing`, `related`, `duplicate`), `CaseNoteVisibility` (`internal`, `confidential`, `restricted`, `public`).
- Model Schemas: `CaseRead`, `PaginatedCasesRead`, `CaseCreate`, `CaseUpdate`, `CaseAssignRequest`, `CaseIncidentRead`, `CaseEvidenceItemRead`, `LegalHoldRead`, `CaseNoteRead`, `CaseNoteCreate`, `CaseTransitionRequest`, `CaseReviewSubmitRequest`, `CaseReviewDecisionRequest`, `LegalHoldCreate`, `LegalHoldRelease`, `CaseTimelineEventRead`, `CaseTimelineResponse`.
- Constants: `AI_ADVISORY_DISCLAIMER` preserved from `backend/app/core/case.py`.

### 2.2 Case API Client (`frontend/src/api/case.ts`)
- `listCases(params)`: Queries `/cases` with department-scoped pagination, text search, status, priority, and legal hold filtering.
- `getCase(caseId)`: Fetches a single case file by UUID.
- `getCaseByReference(ref)`: Lookups case file by unique human-readable case reference (e.g. `CASE-2026-XXXX`).
- `createCase(payload)`: Initiates a new investigation case.
- `updateCase(caseId, payload)`: Modifies title, summary, priority with optimistic locking (`expected_version_id`).
- `assignCase(caseId, payload)`: Assigns lead investigator, supporting supervisor override and rationales.
- `listAssignments(caseId)`: Retrieves case assignment audit history.
- `listCaseIncidents(caseId)` / `linkIncident` / `unlinkIncident`: Manages multi-incident correlation with link types and notes.
- `listCaseEvidence(caseId)` / `linkEvidence` / `unlinkEvidence`: Manages linked evidence items, capturing transfer of custody.
- `placeLegalHold(caseId, payload)` / `releaseLegalHold(caseId, holdId, payload)` / `listCaseLegalHolds(caseId)`: Manages evidentiary litigation holds preventing deletion/purging.
- `listCaseNotes(caseId)` / `createCaseNote(caseId, payload)`: Manages append-only investigator notes with visibility tiers (`internal`, `confidential`, `restricted`, `public`).
- `listCaseFindings(caseId)`: Queries non-authoritative candidate findings and reviewed annotations.
- `transitionCaseStatus(caseId, payload)` / `submitCaseForReview(caseId, payload)` / `approveCaseTransition(caseId, payload)` / `closeCase(caseId, payload)` / `reopenCase(caseId, payload)`: Consequential workflow state transitions with optimistic concurrency versioning.
- `getCaseActivityTimeline(caseId, params)`: Queries unified, chronological operational and chain-of-custody timeline.

### 2.3 Case Components (`frontend/src/components/case/`)
- `CaseListTable.tsx`:
  - Department-scoped case index with real-time text query, status filtering, priority filtering, and legal hold toggle.
  - Paginated table showing case reference, title, priority badge, status badge, active legal hold badge, investigator ID, updated timestamp, and dossier action link.
  - Accessible empty, loading (skeleton rows), and error states.
- `CaseDossierView.tsx`:
  - Full-featured case dossier container with sticky metadata header: title, reference badge, priority badge, status badge, legal hold indicator, version badge, and last updated date.
  - Tabbed interface (`Overview`, `Incidents`, `Evidence`, `Notes`, `Timeline`):
    - **Overview:** Case summary, lead investigator, department, consequential action toolbar (`Submit for Review`, `Transition Status`, `Reassign Investigator`, `Place Legal Hold`), statutory notices.
    - **Incidents:** Linked incidents table showing incident ID, link type badge, linked timestamp, unlink action, and an inline modal form to correlate new incidents.
    - **Evidence:** Enriched evidence inventory showing filename, file size, SHA-256 digest (monospace), scan status badge (`clean`, `infected`, `quarantined`), integrity status (`verified`), custody events count, legal hold indicator, and link/unlink dialogs.
    - **Notes:** Append-only case notes ledger with visibility badges, author ID, timestamp, and an inline form to append new notes.
    - **Timeline:** Embedded chain-of-custody and audit event stream.
- `CaseTimelineView.tsx`:
  - Chronological timeline feed structured as an ordered list (`role="list"`).
  - Explicit sequence numbers (`#1`, `#2`, ...), timestamp, actor identity (`actor_role`, `actor_id`).
  - Distinct badges for Custody Transfer vs Standard Status vs Assignment vs Legal Hold events.
  - Outcome markers (`success`, `failure`, `warning`).
  - Metadata attribute inspector and pagination controls.
  - "Incomplete History" indicator when events may be truncated or pending verification; zero synthesized placeholder events.
- `CaseActionDialogs.tsx`:
  - `StatusTransitionDialog`: State transition with optimistic version passing and rationale requirement.
  - `AssignInvestigatorDialog`: Investigator reassignment with optional supervisor override flag and rationale.
  - `SubmitForReviewDialog`: Escalation to supervisory review queue.
  - `LegalHoldDialog`: Legal hold placement with legal hold reference and reason.
- `CaseCreateModal.tsx`:
  - Modal form to initiate a new case with title, summary, priority, optional investigator assignment, and optional initial incident linkage.

### 2.4 Navigation & Routing (`frontend/src/router/routes.tsx` & `frontend/src/pages/CasesPage.tsx`)
- `/cases` route connected to `CasesPage`.
- Protected by `RoleRouteGuard` allowing only `ROLE_INVESTIGATOR`, `ROLE_DEPT_ADMIN`, and `ROLE_SUPER_ADMIN`.
- Top-level `CasesPage` manages view switching between `CaseListTable` and `CaseDossierView` with URL query-parameter synchronization (`?caseId=...`) and accessible breadcrumbs.
- Navigation header links updated to point to `/cases`.

---

## 3. Mandatory Safety & Evidentiary Invariants

1. **Biometric Surveillance Prohibition:** `BIOMETRIC_MATCHING_ENABLED = False` strictly enforced and maintained. No face identification, 1:N biometric search, suspect profiling, or surveillance capabilities exist in any case or timeline view.
2. **AI Predictions Remain Non-Authoritative:** AI findings in case dossiers are labeled with explicit statutory warnings (`AI_ADVISORY_DISCLAIMER`), noting that all automated detections are purely advisory and cannot determine culpability or legal liability.
3. **Optimistic Concurrency & Audit Integrity:** All consequential case mutations pass `expected_version_id` to prevent concurrent modification collisions. State transitions produce immutable, append-only audit events.
4. **Separation of Duties:** UI respects backend rules prohibiting case investigators from self-approving their own submissions for supervisory review.
5. **No Synthesized Timeline Events:** The activity timeline displays only verified backend events returned by the server; it does not fabricate custody records.

---

## 4. Verification & Quality Gates

### 4.1 Frontend Test Suite
- Total Test Suites: **16 passed (16)**
- Total Tests: **103 passed (103)**
- Phase 115 Test Suites:
  - `frontend/src/test/caseApi.test.ts`: 11 tests verifying all API client methods, query string formatting, error propagation.
  - `frontend/src/test/caseDossier.test.tsx`: 5 tests verifying tab navigation, metadata display, incident listing, evidence listing, notes submission, and timeline integration.
  - `frontend/src/test/casesPage.test.tsx`: 4 tests verifying table rendering, filter interactions, URL parameter sync, create modal launch, and dossier selection.

### 4.2 Frontend Tooling Verification
- **TypeScript:** `npm --prefix frontend run typecheck` passed with 0 errors.
- **ESLint:** `npm --prefix frontend run lint` passed with 0 errors.
- **Vite Build:** `npm --prefix frontend run build` completed cleanly in 9.21s (`dist/assets/index-*.js`, gzip: 114.77 kB).

### 4.3 Backend Regression Verification
- Case Domain & Workflow Tests: **298 passed** (`pytest tests/unit/cases/` in 18.84s).
- Incident & Evidence Tests: **159 passed** (`pytest tests/unit/incidents/ tests/unit/evidence/` in 4.23s).
- Total Backend Regressions Checked: **457 passed, 0 failures**.

---

## 5. Limitations & Future Scope (Phases 116–120)

- **Phase 116 (AI Review & Decision Workflows):** Candidate AI segment video playback, frame-accurate bounding boxes, and human review forms remain to be built in Phase 116.
- **Phase 117 (Analytics & Dashboards UI):** Aggregate metrics, department caseload charts, and SLA monitoring dashboards are scheduled for Phase 117.
- **Phase 118 (Audit Log & Administration UI):** Global system audit viewer, user access control management, and department settings are scheduled for Phase 118.
- **Phase 119 (E2E Browser Testing):** Full browser-level Playwright integration tests spanning intake-to-dossier lifecycle are scheduled for Phase 119.
- **Phase 120 (Production Handover):** Final end-to-end certification and deployment runbooks are scheduled for Phase 120.
- **Overall Production Readiness:** Remains **NO-GO** pending completion of remaining Batch 12 phases and AI classifier weight training.
