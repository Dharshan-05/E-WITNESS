import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  listCases,
  getCase,
  getCaseByReference,
  createCase,
  updateCase,
  assignCase,
  listAssignments,
  listCaseIncidents,
  linkIncident,
  unlinkIncident,
  listCaseEvidence,
  linkEvidence,
  unlinkEvidence,
  placeLegalHold,
  releaseLegalHold,
  listCaseLegalHolds,
  listCaseNotes,
  createCaseNote,
  listCaseFindings,
  transitionCaseStatus,
  submitCaseForReview,
  approveCaseTransition,
  closeCase,
  reopenCase,
  getCaseActivityTimeline,
} from '../api/case';
import { apiClient } from '../api/client';
import type {
  CaseRead,
  PaginatedCasesRead,
  CaseIncidentRead,
  CaseEvidenceItemRead,
  CaseNoteRead,
  CaseTimelineResponse,
  LegalHoldRead,
} from '../types/case';

describe('Case API Client', () => {
  const caseId = '11111111-1111-1111-1111-111111111111';
  const incidentId = '22222222-2222-2222-2222-222222222222';
  const evidenceId = '33333333-3333-3333-3333-333333333333';
  const holdId = '44444444-4444-4444-4444-444444444444';

  const mockCase: CaseRead = {
    id: caseId,
    reference_number: 'CASE-2026-00001',
    title: 'North Annex Investigation',
    summary: 'Detailed investigation into unauthorized access in lab 204.',
    status: 'under_investigation',
    priority: 'high',
    department_id: 'dept-01',
    created_by_id: 'user-01',
    lead_investigator_id: 'inv-01',
    version_id: 2,
    is_legal_hold: false,
    legal_hold_reason: null,
    closed_at: null,
    created_at: '2026-10-28T12:00:00Z',
    updated_at: '2026-10-28T12:30:00Z',
    incidents_count: 1,
    evidence_count: 2,
    ai_segments_count: 0,
    department_name: 'Campus Safety',
    lead_investigator_name: 'Lead Detective',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('listCases calls GET /cases with query parameters', async () => {
    const mockPaginated: PaginatedCasesRead = {
      items: [mockCase],
      total: 1,
      limit: 20,
      offset: 0,
    };

    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue(mockPaginated);

    const result = await listCases({ status: 'open', priority: 'high', limit: 20, offset: 0 });
    expect(getSpy).toHaveBeenCalledWith('/cases', {
      params: { status: 'open', priority: 'high', limit: 20, offset: 0 },
    });
    expect(result).toEqual(mockPaginated);
  });

  it('getCase and getCaseByReference fetch by UUID and reference string', async () => {
    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue(mockCase);

    const byId = await getCase(caseId);
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}`);
    expect(byId).toEqual(mockCase);

    const byRef = await getCaseByReference('CASE-2026-00001');
    expect(getSpy).toHaveBeenCalledWith('/cases/ref/CASE-2026-00001');
    expect(byRef).toEqual(mockCase);
  });

  it('createCase and updateCase execute POST and PATCH requests', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockCase);
    const createPayload = { title: 'New Case', summary: 'Factual summary details.' };
    const created = await createCase(createPayload);
    expect(postSpy).toHaveBeenCalledWith('/cases', createPayload);
    expect(created).toEqual(mockCase);

    const patchSpy = vi.spyOn(apiClient, 'patch').mockResolvedValue({ ...mockCase, version_id: 3 });
    const updatePayload = { title: 'Updated Title', expected_version: 2 };
    const updated = await updateCase(caseId, updatePayload);
    expect(patchSpy).toHaveBeenCalledWith(`/cases/${caseId}`, updatePayload);
    expect(updated.version_id).toBe(3);
  });

  it('assignCase and listAssignments manage investigator assignments', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockCase);
    const assignPayload = { new_investigator_id: 'inv-02', expected_version: 2 };
    await assignCase(caseId, assignPayload);
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/assignments`, assignPayload);

    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue([]);
    await listAssignments(caseId);
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}/assignments`);
  });

  it('manages linked incidents via listCaseIncidents, linkIncident, and unlinkIncident', async () => {
    const mockIncidentLink: CaseIncidentRead = {
      id: 'link-01',
      case_id: caseId,
      incident_id: incidentId,
      linked_by_id: 'user-01',
      link_type: 'primary',
      created_at: '2026-10-28T12:00:00Z',
    };

    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue([mockIncidentLink]);
    const list = await listCaseIncidents(caseId);
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}/incidents`);
    expect(list).toEqual([mockIncidentLink]);

    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockIncidentLink);
    const linkRes = await linkIncident(caseId, { incident_id: incidentId });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/incidents`, { incident_id: incidentId });
    expect(linkRes).toEqual(mockIncidentLink);

    const delSpy = vi.spyOn(apiClient, 'delete').mockResolvedValue({});
    await unlinkIncident(caseId, incidentId);
    expect(delSpy).toHaveBeenCalledWith(`/cases/${caseId}/incidents/${incidentId}`);
  });

  it('manages case evidence and legal holds', async () => {
    const mockEvidence: CaseEvidenceItemRead = {
      id: 'case-evi-01',
      case_id: caseId,
      evidence_id: evidenceId,
      linked_by_id: 'user-01',
      is_exhibiting: true,
      created_at: '2026-10-28T12:00:00Z',
      file_name: 'security.mp4',
      file_size_bytes: 10485760,
      content_type: 'video/mp4',
      sha256_hash: 'f'.repeat(64),
      integrity_status: 'verified',
      is_legal_hold: false,
      chain_of_custody_events_count: 3,
      evidence_status: 'attached',
      active_hold_ids: [],
      active_holds_count: 0,
      audit_event_count: 2,
    };

    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue([mockEvidence]);
    const eviList = await listCaseEvidence(caseId);
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}/evidence`);
    expect(eviList).toEqual([mockEvidence]);

    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockEvidence);
    await linkEvidence(caseId, { evidence_id: evidenceId });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/evidence`, { evidence_id: evidenceId });

    const delSpy = vi.spyOn(apiClient, 'delete').mockResolvedValue({});
    await unlinkEvidence(caseId, evidenceId);
    expect(delSpy).toHaveBeenCalledWith(`/cases/${caseId}/evidence/${evidenceId}`);

    // Legal hold placement and release
    const mockHold: LegalHoldRead = {
      id: holdId,
      hold_reference: 'HOLD-2026-00001',
      case_id: caseId,
      evidence_id: evidenceId,
      department_id: 'dept-01',
      status: 'active',
      reason: 'Formal litigation hold notice',
      placed_by_id: 'user-01',
      placed_at: '2026-10-28T12:00:00Z',
      created_at: '2026-10-28T12:00:00Z',
      updated_at: '2026-10-28T12:00:00Z',
    };

    postSpy.mockResolvedValueOnce(mockHold);
    const holdRes = await placeLegalHold(caseId, evidenceId, { reason: 'Formal litigation hold notice' });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/evidence/${evidenceId}/holds`, {
      reason: 'Formal litigation hold notice',
    });
    expect(holdRes).toEqual(mockHold);

    postSpy.mockResolvedValueOnce({ ...mockHold, status: 'released' });
    const releaseRes = await releaseLegalHold(caseId, evidenceId, holdId, { release_reason: 'Court matter resolved' });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/evidence/${evidenceId}/holds/${holdId}/release`, {
      release_reason: 'Court matter resolved',
    });
    expect(releaseRes.status).toBe('released');

    getSpy.mockResolvedValueOnce([mockHold]);
    const holds = await listCaseLegalHolds(caseId, 'active');
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}/holds`, { params: { status: 'active' } });
    expect(holds).toEqual([mockHold]);
  });

  it('manages case notes and findings', async () => {
    const mockNote: CaseNoteRead = {
      id: 'note-01',
      case_id: caseId,
      author_id: 'user-01',
      visibility: 'internal',
      content: 'Interview completed with witness.',
      version_id: 1,
      is_archived: false,
      evidence_reference_ids: [],
      created_at: '2026-10-28T12:00:00Z',
      updated_at: '2026-10-28T12:00:00Z',
    };

    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue([mockNote]);
    const notes = await listCaseNotes(caseId);
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}/notes`);
    expect(notes).toEqual([mockNote]);

    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockNote);
    const createdNote = await createCaseNote(caseId, { content: 'Interview completed with witness.' });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/notes`, { content: 'Interview completed with witness.' });
    expect(createdNote).toEqual(mockNote);

    getSpy.mockResolvedValueOnce([]);
    await listCaseFindings(caseId);
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}/findings`);
  });

  it('executes case transitions, submissions, approvals, close, and reopen', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockCase);

    await transitionCaseStatus(caseId, {
      target_status: 'resolved',
      reason: 'Investigation concluded with clear findings.',
      expected_version_id: 2,
    });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/transition`, {
      target_status: 'resolved',
      reason: 'Investigation concluded with clear findings.',
      expected_version_id: 2,
    });

    await submitCaseForReview(caseId, {
      reason: 'All evidence verified; submitting for supervisor review.',
      expected_version_id: 2,
    });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/submit-for-review`, {
      reason: 'All evidence verified; submitting for supervisor review.',
      expected_version_id: 2,
    });

    await approveCaseTransition(caseId, {
      decision: 'approved',
      rationale: 'Findings substantiated and verified.',
    });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/approvals`, {
      decision: 'approved',
      rationale: 'Findings substantiated and verified.',
    });

    await closeCase(caseId, {
      reason: 'Administrative disposition formal closure.',
      expected_version_id: 2,
    });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/close`, {
      reason: 'Administrative disposition formal closure.',
      expected_version_id: 2,
    });

    await reopenCase(caseId, {
      reason: 'New corroborating evidence surfaced.',
      expected_version_id: 2,
    });
    expect(postSpy).toHaveBeenCalledWith(`/cases/${caseId}/reopen`, {
      reason: 'New corroborating evidence surfaced.',
      expected_version_id: 2,
    });
  });

  it('retrieves activity timeline via getCaseActivityTimeline', async () => {
    const mockTimeline: CaseTimelineResponse = {
      items: [
        {
          id: 'evt-01',
          case_id: caseId,
          case_reference: 'CASE-2026-00001',
          event_type: 'case:status:transition',
          timestamp: '2026-10-28T12:00:00Z',
          sequence_number: 1,
          actor_id: 'user-01',
          actor_role: 'investigator',
          outcome: 'success',
          summary: 'Case transition to under_investigation',
          details: { from_status: 'draft', to_status: 'under_investigation' },
        },
      ],
      total_count: 1,
      next_cursor: null,
      has_more: false,
    };

    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue(mockTimeline);

    const timeline = await getCaseActivityTimeline(caseId, { limit: 50, ascending: false });
    expect(getSpy).toHaveBeenCalledWith(`/cases/${caseId}/timeline`, {
      params: { limit: 50, ascending: false },
    });
    expect(timeline).toEqual(mockTimeline);
  });
});
