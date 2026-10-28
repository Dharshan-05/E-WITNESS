import { apiClient } from './client';
import type {
  CaseRead,
  PaginatedCasesRead,
  CaseListParams,
  CaseCreate,
  CaseUpdate,
  CaseAssignRequest,
  CaseAssignmentRead,
  CaseIncidentRead,
  CaseLinkIncidentRequest,
  CaseEvidenceItemRead,
  CaseLinkEvidenceRequest,
  LegalHoldRead,
  LegalHoldPlaceRequest,
  LegalHoldReleaseRequest,
  CaseNoteRead,
  CaseNoteCreate,
  CaseFindingRead,
  CaseFindingCreate,
  CaseFindingUpdate,
  CaseFindingHistoryRead,
  CaseAISegmentRead,
  CaseAISegmentReviewRequest,
  CaseCreateAISegmentAnnotationRequest,
  CaseAISegmentHistoryItemRead,
  CaseTransitionRequest,
  CaseSubmitReviewRequest,
  CaseApprovalRequest,
  CaseApprovalRead,
  CaseCloseRequest,
  CaseReopenRequest,
  CaseTimelineResponse,
  CaseTimelineParams,
} from '../types/case';

/**
 * List paginated investigation cases scoped to caller's department or assignments.
 * GET /cases
 */
export async function listCases(params?: CaseListParams): Promise<PaginatedCasesRead> {
  return apiClient.get<PaginatedCasesRead>('/cases', {
    params: params as Record<string, string | number | boolean | undefined | null>,
  });
}

/**
 * Retrieve a case by UUID with relational linkages.
 * GET /cases/{case_id}
 */
export async function getCase(caseId: string): Promise<CaseRead> {
  return apiClient.get<CaseRead>(`/cases/${encodeURIComponent(caseId)}`);
}

/**
 * Retrieve a case by formatted reference number.
 * GET /cases/ref/{reference_number}
 */
export async function getCaseByReference(referenceNumber: string): Promise<CaseRead> {
  return apiClient.get<CaseRead>(`/cases/ref/${encodeURIComponent(referenceNumber)}`);
}

/**
 * Create a new investigation case.
 * POST /cases
 */
export async function createCase(payload: CaseCreate): Promise<CaseRead> {
  return apiClient.post<CaseRead>('/cases', payload);
}

/**
 * Update case details or status with optimistic locking.
 * PATCH /cases/{case_id}
 */
export async function updateCase(caseId: string, payload: CaseUpdate): Promise<CaseRead> {
  return apiClient.patch<CaseRead>(`/cases/${encodeURIComponent(caseId)}`, payload);
}

/**
 * Assign or transfer lead investigator.
 * POST /cases/{case_id}/assignments
 */
export async function assignCase(
  caseId: string,
  payload: CaseAssignRequest
): Promise<CaseRead> {
  return apiClient.post<CaseRead>(`/cases/${encodeURIComponent(caseId)}/assignments`, payload);
}

/**
 * List append-only assignment history.
 * GET /cases/{case_id}/assignments
 */
export async function listAssignments(caseId: string): Promise<CaseAssignmentRead[]> {
  return apiClient.get<CaseAssignmentRead[]>(
    `/cases/${encodeURIComponent(caseId)}/assignments`
  );
}

/**
 * List linked incidents for an investigation case.
 * GET /cases/{case_id}/incidents
 */
export async function listCaseIncidents(caseId: string): Promise<CaseIncidentRead[]> {
  return apiClient.get<CaseIncidentRead[]>(
    `/cases/${encodeURIComponent(caseId)}/incidents`
  );
}

/**
 * Link an incident to a case.
 * POST /cases/{case_id}/incidents
 */
export async function linkIncident(
  caseId: string,
  payload: CaseLinkIncidentRequest
): Promise<CaseIncidentRead> {
  return apiClient.post<CaseIncidentRead>(
    `/cases/${encodeURIComponent(caseId)}/incidents`,
    payload
  );
}

/**
 * Unlink an incident from a case.
 * DELETE /cases/{case_id}/incidents/{incident_id}
 */
export async function unlinkIncident(
  caseId: string,
  incidentId: string
): Promise<void> {
  await apiClient.delete(
    `/cases/${encodeURIComponent(caseId)}/incidents/${encodeURIComponent(incidentId)}`
  );
}

/**
 * List enriched evidence inventory for a case.
 * GET /cases/{case_id}/evidence
 */
export async function listCaseEvidence(caseId: string): Promise<CaseEvidenceItemRead[]> {
  return apiClient.get<CaseEvidenceItemRead[]>(
    `/cases/${encodeURIComponent(caseId)}/evidence`
  );
}

/**
 * Link existing evidence attachment to a case.
 * POST /cases/{case_id}/evidence
 */
export async function linkEvidence(
  caseId: string,
  payload: CaseLinkEvidenceRequest
): Promise<CaseEvidenceItemRead> {
  return apiClient.post<CaseEvidenceItemRead>(
    `/cases/${encodeURIComponent(caseId)}/evidence`,
    payload
  );
}

/**
 * Unlink evidence from a case.
 * DELETE /cases/{case_id}/evidence/{evidence_id}
 */
export async function unlinkEvidence(
  caseId: string,
  evidenceId: string
): Promise<void> {
  await apiClient.delete(
    `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}`
  );
}

/**
 * Place an audited legal hold on case evidence.
 * POST /cases/{case_id}/evidence/{evidence_id}/holds
 */
export async function placeLegalHold(
  caseId: string,
  evidenceId: string,
  payload: LegalHoldPlaceRequest
): Promise<LegalHoldRead> {
  return apiClient.post<LegalHoldRead>(
    `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/holds`,
    payload
  );
}

/**
 * Release an active legal hold on evidence.
 * POST /cases/{case_id}/evidence/{evidence_id}/holds/{hold_id}/release
 */
export async function releaseLegalHold(
  caseId: string,
  evidenceId: string,
  holdId: string,
  payload: LegalHoldReleaseRequest
): Promise<LegalHoldRead> {
  return apiClient.post<LegalHoldRead>(
    `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/holds/${encodeURIComponent(holdId)}/release`,
    payload
  );
}

/**
 * List all legal holds for a case.
 * GET /cases/{case_id}/holds
 */
export async function listCaseLegalHolds(
  caseId: string,
  status?: string
): Promise<LegalHoldRead[]> {
  return apiClient.get<LegalHoldRead[]>(`/cases/${encodeURIComponent(caseId)}/holds`, {
    params: status ? { status } : undefined,
  });
}

/**
 * List investigation case notes.
 * GET /cases/{case_id}/notes
 */
export async function listCaseNotes(caseId: string): Promise<CaseNoteRead[]> {
  return apiClient.get<CaseNoteRead[]>(`/cases/${encodeURIComponent(caseId)}/notes`);
}

/**
 * Add a new note to a case.
 * POST /cases/{case_id}/notes
 */
export async function createCaseNote(
  caseId: string,
  payload: CaseNoteCreate
): Promise<CaseNoteRead> {
  return apiClient.post<CaseNoteRead>(
    `/cases/${encodeURIComponent(caseId)}/notes`,
    payload
  );
}

/**
 * List structured formal findings for a case.
 * GET /cases/{case_id}/findings
 */
export async function listCaseFindings(caseId: string): Promise<CaseFindingRead[]> {
  return apiClient.get<CaseFindingRead[]>(
    `/cases/${encodeURIComponent(caseId)}/findings`
  );
}

/**
 * Transition case status through the centralized lifecycle state machine.
 * POST /cases/{case_id}/transition
 */
export async function transitionCaseStatus(
  caseId: string,
  payload: CaseTransitionRequest
): Promise<CaseRead> {
  return apiClient.post<CaseRead>(
    `/cases/${encodeURIComponent(caseId)}/transition`,
    payload
  );
}

/**
 * Submit case for supervisory review with readiness validation.
 * POST /cases/{case_id}/submit-for-review
 */
export async function submitCaseForReview(
  caseId: string,
  payload: CaseSubmitReviewRequest
): Promise<CaseRead> {
  return apiClient.post<CaseRead>(
    `/cases/${encodeURIComponent(caseId)}/submit-for-review`,
    payload
  );
}

/**
 * Approve or reject a case transition (supervisors).
 * POST /cases/{case_id}/approvals
 */
export async function approveCaseTransition(
  caseId: string,
  payload: CaseApprovalRequest
): Promise<CaseApprovalRead> {
  return apiClient.post<CaseApprovalRead>(
    `/cases/${encodeURIComponent(caseId)}/approvals`,
    payload
  );
}

/**
 * Formally close an investigation case.
 * POST /cases/{case_id}/close
 */
export async function closeCase(
  caseId: string,
  payload: CaseCloseRequest
): Promise<CaseRead> {
  return apiClient.post<CaseRead>(
    `/cases/${encodeURIComponent(caseId)}/close`,
    payload
  );
}

/**
 * Reopen a closed or resolved case.
 * POST /cases/{case_id}/reopen
 */
export async function reopenCase(
  caseId: string,
  payload: CaseReopenRequest
): Promise<CaseRead> {
  return apiClient.post<CaseRead>(
    `/cases/${encodeURIComponent(caseId)}/reopen`,
    payload
  );
}

/**
 * Retrieve unified case activity timeline, audit history, and chain-of-custody (Phase 88).
 * GET /cases/{case_id}/timeline
 */
export async function getCaseActivityTimeline(
  caseId: string,
  options?: CaseTimelineParams
): Promise<CaseTimelineResponse> {
  return apiClient.get<CaseTimelineResponse>(
    `/cases/${encodeURIComponent(caseId)}/timeline`,
    {
      params: options as Record<string, string | number | boolean | undefined | null>,
    }
  );
}

// ─── AI Candidate Segments & Annotations (Phase 84, 85, 116) ────────────────

/**
 * List all AI candidate segments linked to a case.
 * GET /cases/{case_id}/ai-segments
 */
export async function listCaseAISegments(caseId: string): Promise<CaseAISegmentRead[]> {
  return apiClient.get<CaseAISegmentRead[]>(
    `/cases/${encodeURIComponent(caseId)}/ai-segments`
  );
}

/**
 * Get an individual AI candidate segment linked to a case.
 * GET /cases/{case_id}/ai-segments/{segment_id}
 */
export async function getCaseAISegment(
  caseId: string,
  segmentId: string
): Promise<CaseAISegmentRead> {
  return apiClient.get<CaseAISegmentRead>(
    `/cases/${encodeURIComponent(caseId)}/ai-segments/${encodeURIComponent(segmentId)}`
  );
}

/**
 * List AI candidate segments for a specific evidence item in a case.
 * GET /cases/{case_id}/evidence/{evidence_id}/ai-segments
 */
export async function listCaseEvidenceAISegments(
  caseId: string,
  evidenceId: string
): Promise<CaseAISegmentRead[]> {
  return apiClient.get<CaseAISegmentRead[]>(
    `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/ai-segments`
  );
}

/**
 * Attach an advisory AI candidate segment annotation to case evidence.
 * POST /cases/{case_id}/evidence/{evidence_id}/ai-segments
 */
export async function createCaseEvidenceAISegment(
  caseId: string,
  evidenceId: string,
  payload: CaseCreateAISegmentAnnotationRequest
): Promise<CaseAISegmentRead> {
  return apiClient.post<CaseAISegmentRead>(
    `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/ai-segments`,
    payload
  );
}

/**
 * Record authorized human review on an AI candidate segment.
 * POST /cases/{case_id}/ai-segments/{segment_id}/review
 */
export async function reviewCaseAISegment(
  caseId: string,
  segmentId: string,
  payload: CaseAISegmentReviewRequest
): Promise<CaseAISegmentRead> {
  return apiClient.post<CaseAISegmentRead>(
    `/cases/${encodeURIComponent(caseId)}/ai-segments/${encodeURIComponent(segmentId)}/review`,
    payload
  );
}

/**
 * Record authorized supervisor override of an existing AI segment review determination.
 * POST /cases/{case_id}/ai-segments/{segment_id}/override
 */
export async function overrideCaseAISegment(
  caseId: string,
  segmentId: string,
  payload: CaseAISegmentReviewRequest
): Promise<CaseAISegmentRead> {
  return apiClient.post<CaseAISegmentRead>(
    `/cases/${encodeURIComponent(caseId)}/ai-segments/${encodeURIComponent(segmentId)}/override`,
    payload
  );
}

/**
 * Retrieve review determination audit history for an AI candidate segment.
 * GET /cases/{case_id}/ai-segments/{segment_id}/history
 */
export async function getCaseAISegmentReviewHistory(
  caseId: string,
  segmentId: string
): Promise<CaseAISegmentHistoryItemRead[]> {
  return apiClient.get<CaseAISegmentHistoryItemRead[]>(
    `/cases/${encodeURIComponent(caseId)}/ai-segments/${encodeURIComponent(segmentId)}/history`
  );
}

/**
 * Unlink an AI candidate segment from a case.
 * DELETE /cases/{case_id}/ai-segments/{segment_id}
 */
export async function unlinkCaseAISegment(
  caseId: string,
  segmentId: string
): Promise<void> {
  await apiClient.delete(
    `/cases/${encodeURIComponent(caseId)}/ai-segments/${encodeURIComponent(segmentId)}`
  );
}

// ─── Case Findings (Phase 86, 116) ──────────────────────────────────────────

/**
 * Record a formal investigation finding with evidence and AI segment linkages.
 * POST /cases/{case_id}/findings
 */
export async function createCaseFinding(
  caseId: string,
  payload: CaseFindingCreate
): Promise<CaseFindingRead> {
  return apiClient.post<CaseFindingRead>(
    `/cases/${encodeURIComponent(caseId)}/findings`,
    payload
  );
}

/**
 * Edit an investigation finding with optimistic locking.
 * PATCH /cases/{case_id}/findings/{finding_id}
 */
export async function updateCaseFinding(
  caseId: string,
  findingId: string,
  payload: CaseFindingUpdate
): Promise<CaseFindingRead> {
  return apiClient.patch<CaseFindingRead>(
    `/cases/${encodeURIComponent(caseId)}/findings/${encodeURIComponent(findingId)}`,
    payload
  );
}

/**
 * View audit log of historical modifications made to an investigation finding.
 * GET /cases/{case_id}/findings/{finding_id}/history
 */
export async function getCaseFindingHistory(
  caseId: string,
  findingId: string
): Promise<CaseFindingHistoryRead[]> {
  return apiClient.get<CaseFindingHistoryRead[]>(
    `/cases/${encodeURIComponent(caseId)}/findings/${encodeURIComponent(findingId)}/history`
  );
}
