import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  listCaseAISegments,
  getCaseAISegment,
  listCaseEvidenceAISegments,
  createCaseEvidenceAISegment,
  reviewCaseAISegment,
  overrideCaseAISegment,
  getCaseAISegmentReviewHistory,
  unlinkCaseAISegment,
  createCaseFinding,
  updateCaseFinding,
  getCaseFindingHistory,
} from '../api/case';
import { getAttachmentDownloadUrl } from '../api/evidence';
import { apiClient } from '../api/client';
import type {
  CaseAISegmentRead,
  CaseAISegmentReviewRequest,
  CaseCreateAISegmentAnnotationRequest,
  CaseAISegmentHistoryItemRead,
  CaseFindingCreate,
  CaseFindingRead,
  CaseFindingHistoryRead,
} from '../types/case';
import type { EvidenceDownloadResponse } from '../types/evidence';

describe('Case AI & Video Review API Client', () => {
  const caseId = '11111111-1111-1111-1111-111111111111';
  const evidenceId = '22222222-2222-2222-2222-222222222222';
  const segmentId = '33333333-3333-3333-3333-333333333333';
  const findingId = '44444444-4444-4444-4444-444444444444';
  const incidentId = '55555555-5555-5555-5555-555555555555';

  const mockAISegment: CaseAISegmentRead = {
    id: 'link-1',
    case_id: caseId,
    segment_id: segmentId,
    linked_by_id: 'user-1',
    investigative_relevance: 'candidate_lead',
    relevance_notes: 'Initial automated violence candidate detection.',
    created_at: '2026-10-28T12:00:00Z',
    job_id: 'job-1',
    evidence_id: evidenceId,
    incident_id: incidentId,
    start_seconds: 12.5,
    end_seconds: 18.2,
    duration_seconds: 5.7,
    score: 0.88,
    raw_score: 0.88,
    calibrated_score: 0.82,
    label: 'violence',
    model_name: 'violence-classifier',
    model_version: '1.0.0',
    review_status: 'pending_review',
    decision_revision: 1,
    is_override: false,
    advisory_disclaimer:
      'AI violence detection annotations are probabilistic investigative leads only.',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('lists AI candidate segments for a case', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce([mockAISegment]);

    const result = await listCaseAISegments(caseId);

    expect(apiClient.get).toHaveBeenCalledWith(`/cases/${caseId}/ai-segments`);
    expect(result).toHaveLength(1);
    expect(result[0].start_seconds).toBe(12.5);
  });

  it('gets an individual AI candidate segment', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockAISegment);

    const result = await getCaseAISegment(caseId, segmentId);

    expect(apiClient.get).toHaveBeenCalledWith(
      `/cases/${caseId}/ai-segments/${segmentId}`
    );
    expect(result.id).toBe('link-1');
  });

  it('lists AI candidate segments for a specific evidence item', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce([mockAISegment]);

    const result = await listCaseEvidenceAISegments(caseId, evidenceId);

    expect(apiClient.get).toHaveBeenCalledWith(
      `/cases/${caseId}/evidence/${evidenceId}/ai-segments`
    );
    expect(result).toHaveLength(1);
  });

  it('creates an advisory AI candidate segment annotation on case evidence', async () => {
    const payload: CaseCreateAISegmentAnnotationRequest = {
      evidence_id: evidenceId,
      start_seconds: 10.0,
      end_seconds: 15.0,
      raw_score: 0.91,
      raw_label: 'possible_violence',
      model_name: 'violence-classifier',
      model_version: '1.0.0',
    };
    vi.spyOn(apiClient, 'post').mockResolvedValueOnce(mockAISegment);

    const result = await createCaseEvidenceAISegment(caseId, evidenceId, payload);

    expect(apiClient.post).toHaveBeenCalledWith(
      `/cases/${caseId}/evidence/${evidenceId}/ai-segments`,
      payload
    );
    expect(result.evidence_id).toBe(evidenceId);
  });

  it('records authorized human review on an AI candidate segment', async () => {
    const payload: CaseAISegmentReviewRequest = {
      review_status: 'confirmed',
      review_rationale: 'Physical struggle corroborated on camera 2.',
      expected_review_status: 'pending_review',
      expected_revision: 1,
    };
    const confirmedSegment = {
      ...mockAISegment,
      review_status: 'confirmed',
      decision_revision: 2,
    };
    vi.spyOn(apiClient, 'post').mockResolvedValueOnce(confirmedSegment);

    const result = await reviewCaseAISegment(caseId, segmentId, payload);

    expect(apiClient.post).toHaveBeenCalledWith(
      `/cases/${caseId}/ai-segments/${segmentId}/review`,
      payload
    );
    expect(result.review_status).toBe('confirmed');
    expect(result.decision_revision).toBe(2);
  });

  it('records supervisor override of an existing review determination', async () => {
    const payload: CaseAISegmentReviewRequest = {
      review_status: 'rejected',
      review_rationale: 'Supervisor review: accidental collision, not physical altercation.',
      is_override: true,
      expected_review_status: 'confirmed',
      expected_revision: 2,
    };
    const overriddenSegment = {
      ...mockAISegment,
      review_status: 'rejected',
      is_override: true,
      decision_revision: 3,
    };
    vi.spyOn(apiClient, 'post').mockResolvedValueOnce(overriddenSegment);

    const result = await overrideCaseAISegment(caseId, segmentId, payload);

    expect(apiClient.post).toHaveBeenCalledWith(
      `/cases/${caseId}/ai-segments/${segmentId}/override`,
      payload
    );
    expect(result.review_status).toBe('rejected');
    expect(result.is_override).toBe(true);
  });

  it('retrieves review determination audit history for an AI segment', async () => {
    const historyItem: CaseAISegmentHistoryItemRead = {
      event_id: 'ev-1',
      timestamp: '2026-10-28T14:00:00Z',
      actor_id: 'user-2',
      actor_role: 'investigator',
      previous_review_status: 'pending_review',
      new_review_status: 'confirmed',
      review_rationale: 'Reviewed and confirmed.',
      is_override: false,
      decision_revision: 1,
    };
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce([historyItem]);

    const result = await getCaseAISegmentReviewHistory(caseId, segmentId);

    expect(apiClient.get).toHaveBeenCalledWith(
      `/cases/${caseId}/ai-segments/${segmentId}/history`
    );
    expect(result).toHaveLength(1);
    expect(result[0].new_review_status).toBe('confirmed');
  });

  it('unlinks an AI candidate segment from a case', async () => {
    vi.spyOn(apiClient, 'delete').mockResolvedValueOnce(undefined);

    await unlinkCaseAISegment(caseId, segmentId);

    expect(apiClient.delete).toHaveBeenCalledWith(
      `/cases/${caseId}/ai-segments/${segmentId}`
    );
  });

  it('records a formal investigation finding with evidence and AI linkages', async () => {
    const payload: CaseFindingCreate = {
      finding_type: 'inculpatory',
      title: 'Corroborated entry dispute',
      description: 'Physical confrontation verified at east entrance turnstiles.',
      evidence_ids: [evidenceId],
      ai_segment_ids: [segmentId],
      incident_ids: [incidentId],
      is_preliminary: true,
    };
    const mockFinding: CaseFindingRead = {
      id: findingId,
      case_id: caseId,
      author_id: 'user-1',
      finding_type: 'inculpatory',
      title: 'Corroborated entry dispute',
      description: 'Physical confrontation verified at east entrance turnstiles.',
      evidence_ids: [evidenceId],
      ai_segment_ids: [segmentId],
      incident_ids: [incidentId],
      version_id: 1,
      is_preliminary: true,
      created_at: '2026-10-28T15:00:00Z',
      updated_at: '2026-10-28T15:00:00Z',
    };
    vi.spyOn(apiClient, 'post').mockResolvedValueOnce(mockFinding);

    const result = await createCaseFinding(caseId, payload);

    expect(apiClient.post).toHaveBeenCalledWith(
      `/cases/${caseId}/findings`,
      payload
    );
    expect(result.id).toBe(findingId);
    expect(result.finding_type).toBe('inculpatory');
  });

  it('updates an investigation finding with optimistic locking', async () => {
    const updatePayload = {
      title: 'Updated title',
      expected_version_id: 1,
    };
    const updatedFinding: CaseFindingRead = {
      id: findingId,
      case_id: caseId,
      author_id: 'user-1',
      finding_type: 'inculpatory',
      title: 'Updated title',
      description: 'Physical confrontation verified at east entrance turnstiles.',
      evidence_ids: [evidenceId],
      ai_segment_ids: [segmentId],
      incident_ids: [incidentId],
      version_id: 2,
      is_preliminary: false,
      created_at: '2026-10-28T15:00:00Z',
      updated_at: '2026-10-28T15:10:00Z',
    };
    vi.spyOn(apiClient, 'patch').mockResolvedValueOnce(updatedFinding);

    const result = await updateCaseFinding(caseId, findingId, updatePayload);

    expect(apiClient.patch).toHaveBeenCalledWith(
      `/cases/${caseId}/findings/${findingId}`,
      updatePayload
    );
    expect(result.version_id).toBe(2);
  });

  it('gets finding audit history', async () => {
    const historyItem: CaseFindingHistoryRead = {
      id: 'fh-1',
      finding_id: findingId,
      version_id: 1,
      editor_id: 'user-1',
      title: 'Original title',
      description: 'Original description',
      reason: 'Initial creation',
      created_at: '2026-10-28T15:00:00Z',
    };
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce([historyItem]);

    const result = await getCaseFindingHistory(caseId, findingId);

    expect(apiClient.get).toHaveBeenCalledWith(
      `/cases/${caseId}/findings/${findingId}/history`
    );
    expect(result).toHaveLength(1);
    expect(result[0].version_id).toBe(1);
  });

  it('generates authorized short-lived download URL for evidence attachment', async () => {
    const mockDownload: EvidenceDownloadResponse = {
      download_url: 'https://storage.e-witness.local/signed/evidence-123.mp4?token=abc',
      filename: 'security_hallway_feed.mp4',
      content_type: 'video/mp4',
      file_size_bytes: 48500000,
      expires_at: '2026-10-28T16:05:00Z',
    };
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockDownload);

    const result = await getAttachmentDownloadUrl(incidentId, evidenceId, 300);

    expect(apiClient.get).toHaveBeenCalledWith(
      `/incidents/${incidentId}/attachments/${evidenceId}/download`,
      { params: { expires_in_seconds: 300 } }
    );
    expect(result.download_url).toContain('https://storage.e-witness.local/signed/');
    expect(result.file_size_bytes).toBe(48500000);
  });
});
