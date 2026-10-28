/**
 * Investigation Case Management Types — Phase 115.
 * Matches backend `backend/app/schemas/case.py` and `backend/app/core/case.py`.
 */

import type { SegmentReviewStatus } from './ai';

// ─── Core Enums ────────────────────────────────────────────────────────────

export type CaseStatus =
  | 'draft'
  | 'open'
  | 'under_investigation'
  | 'pending_review'
  | 'pending_supervisor_review'
  | 'suspended'
  | 'resolved'
  | 'closed'
  | 'reopened';

export type CasePriority = 'low' | 'medium' | 'high' | 'critical';

export type IncidentLinkType = 'primary' | 'related' | 'evidence_source';

export type CaseNoteVisibility =
  | 'public'
  | 'internal'
  | 'confidential'
  | 'restricted';

export type CaseFindingType =
  | 'inculpatory'
  | 'exculpatory'
  | 'procedural'
  | 'inconclusive'
  | 'preliminary';

export type CaseExportScope =
  | 'summary'
  | 'full_investigation'
  | 'evidence_manifest_only'
  | 'court_package';

export type CaseExportFormat = 'json' | 'zip' | 'pdf_summary';

// ─── Case Read & Paginated List ────────────────────────────────────────────

export interface CaseRead {
  id: string;
  reference_number: string;
  title: string;
  summary: string;
  status: CaseStatus;
  priority: CasePriority;
  department_id: string;
  created_by_id: string;
  lead_investigator_id?: string | null;
  version_id: number;
  is_legal_hold: boolean;
  legal_hold_reason?: string | null;
  closed_at?: string | null;
  created_at: string;
  updated_at: string;
  incidents_count: number;
  evidence_count: number;
  ai_segments_count: number;
  department_name?: string | null;
  lead_investigator_name?: string | null;
}

/** Legacy alias for backwards compatibility */
export type Case = CaseRead;

export interface PaginatedCasesRead {
  items: CaseRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface CaseListParams {
  limit?: number;
  offset?: number;
  status?: string | null;
  priority?: string | null;
  is_legal_hold?: boolean | null;
  search?: string | null;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

// ─── Case Mutation Payloads ────────────────────────────────────────────────

export interface CaseCreate {
  title: string;
  summary: string;
  priority?: CasePriority;
  lead_investigator_id?: string | null;
  initial_incident_id?: string | null;
}

export interface CaseUpdate {
  title?: string | null;
  summary?: string | null;
  priority?: CasePriority | null;
  status?: CaseStatus | null;
  status_reason?: string | null;
  is_legal_hold?: boolean | null;
  legal_hold_reason?: string | null;
  expected_version: number;
  is_supervisor_override?: boolean;
  override_justification?: string | null;
}

// ─── Case Assignment ───────────────────────────────────────────────────────

export interface CaseAssignRequest {
  new_investigator_id: string;
  assignment_reason?: string | null;
  expected_version: number;
  is_supervisor_override?: boolean;
  override_justification?: string | null;
}

export interface CaseAssignmentRead {
  id: string;
  case_id: string;
  previous_investigator_id?: string | null;
  new_investigator_id: string;
  assigned_by_id: string;
  assignment_reason?: string | null;
  is_supervisor_override: boolean;
  override_justification?: string | null;
  created_at: string;
}

export interface InvestigatorWorkloadRead {
  investigator_id: string;
  active_cases_count: number;
  max_active_cases: number;
  capacity_available: boolean;
  department_id?: string | null;
}

// ─── Case Incident Linkages ────────────────────────────────────────────────

export interface CaseLinkIncidentRequest {
  incident_id: string;
  link_type?: IncidentLinkType;
}

export interface CaseIncidentRead {
  id: string;
  case_id: string;
  incident_id: string;
  linked_by_id: string;
  link_type: IncidentLinkType;
  created_at: string;
  incident_title?: string | null;
  incident_reference_number?: string | null;
  incident_status?: string | null;
}

// ─── Case Evidence & Legal Hold ────────────────────────────────────────────

export interface CaseLinkEvidenceRequest {
  evidence_id: string;
  notes?: string | null;
  is_exhibiting?: boolean;
}

export interface CaseEvidenceItemRead {
  id: string;
  case_id: string;
  evidence_id: string;
  linked_by_id: string;
  notes?: string | null;
  is_exhibiting: boolean;
  created_at: string;
  file_name: string;
  file_size_bytes: number;
  content_type: string;
  sha256_hash: string;
  integrity_status: string;
  is_legal_hold: boolean;
  chain_of_custody_events_count: number;
  case_reference?: string | null;
  evidence_type?: string | null;
  media_format?: string | null;
  ingested_at?: string | null;
  client_reported_at?: string | null;
  source_description?: string | null;
  evidence_status: string;
  active_hold_ids: string[];
  active_holds_count: number;
  audit_event_count: number;
}

export interface LegalHoldPlaceRequest {
  reason: string;
  notes?: string | null;
}

export interface LegalHoldReleaseRequest {
  release_reason: string;
}

export interface LegalHoldRead {
  id: string;
  hold_reference: string;
  case_id: string;
  evidence_id: string;
  department_id: string;
  status: string;
  reason: string;
  placed_by_id: string;
  placed_at: string;
  released_by_id?: string | null;
  released_at?: string | null;
  release_reason?: string | null;
  created_at: string;
  updated_at: string;
}

// ─── Case Notes ────────────────────────────────────────────────────────────

export interface CaseNoteCreate {
  visibility?: CaseNoteVisibility;
  content: string;
  evidence_reference_ids?: string[];
}

export interface CaseNoteUpdate {
  content: string;
  edit_reason?: string | null;
  expected_version_id: number;
}

export interface CaseNoteRead {
  id: string;
  case_id: string;
  author_id: string;
  visibility: CaseNoteVisibility;
  content: string;
  version_id: number;
  is_archived: boolean;
  evidence_reference_ids: string[];
  created_at: string;
  updated_at: string;
}

// ─── Case Findings ─────────────────────────────────────────────────────────

export interface CaseFindingRead {
  id: string;
  case_id: string;
  author_id?: string;
  finding_type: CaseFindingType | string;
  title: string;
  description: string;
  evidence_ids?: string[];
  ai_segment_ids?: string[];
  incident_ids?: string[];
  version_id?: number;
  is_preliminary: boolean;
  created_at: string;
  updated_at: string;
}

// ─── Case Transitions & Approvals ──────────────────────────────────────────

export interface CaseTransitionRequest {
  target_status: string;
  reason: string;
  expected_version_id: number;
}

export interface CaseSubmitReviewRequest {
  reason: string;
  expected_version_id: number;
}

export interface CaseApprovalRequest {
  decision: 'approved' | 'rejected' | 'returned_for_revision';
  rationale: string;
  to_status?: string | null;
}

export interface CaseApprovalRead {
  id: string;
  case_id: string;
  approver_id: string;
  decision: string;
  from_status: string;
  to_status: string;
  rationale: string;
  created_at: string;
}

export interface CaseCloseRequest {
  reason: string;
  expected_version_id: number;
}

export interface CaseReopenRequest {
  reason: string;
  expected_version_id: number;
  target_status?: CaseStatus;
}

// ─── Activity & Custody Timeline (Phase 88) ────────────────────────────────

export interface CaseTimelineEventRead {
  id: string;
  case_id: string;
  case_reference: string;
  event_type: string;
  timestamp: string;
  sequence_number?: number | null;
  actor_id?: string | null;
  actor_role?: string | null;
  outcome: string;
  summary: string;
  details: Record<string, unknown>;
}

export type CaseTimelineEvent = CaseTimelineEventRead;

export interface CaseTimelineResponse {
  items: CaseTimelineEventRead[];
  total_count: number;
  next_cursor?: string | null;
  has_more: boolean;
}

export interface CaseTimelineParams {
  event_types?: string[];
  actor_id?: string;
  start_time?: string;
  end_time?: string;
  outcome?: string;
  limit?: number;
  cursor?: string;
  ascending?: boolean;
}

// ─── AI Candidate Segments & Annotations (Phase 84, 85, 116) ────────────────

export type InvestigativeRelevance =
  | 'candidate_lead'
  | 'key_evidence'
  | 'corroborating'
  | 'inconclusive'
  | 'refuted'
  | 'excluded';

export interface CaseAISegmentRead {
  id: string;
  case_id: string;
  segment_id: string;
  linked_by_id: string;
  investigative_relevance: InvestigativeRelevance | string;
  relevance_notes?: string | null;
  created_at: string;

  // Provenance & AI Model Outputs
  job_id: string;
  evidence_id: string;
  incident_id: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  score: number;
  raw_score?: number | null;
  calibrated_score?: number | null;
  label: string;
  model_name?: string | null;
  model_version?: string | null;
  preprocessing_version?: string | null;
  calibration_version?: string | null;
  confidence_interpretation?: string;
  original_evidence_digest?: string | null;
  inferred_at?: string | null;
  updated_at?: string | null;

  // Review Status & Determinations
  review_status: SegmentReviewStatus | string;
  reviewed_by_id?: string | null;
  reviewed_at?: string | null;
  review_notes?: string | null;

  original_ai_prediction?: Record<string, unknown>;
  current_human_decision?: Record<string, unknown> | null;
  human_corrected_label?: string | null;
  decision_revision: number;
  is_override: boolean;

  advisory_disclaimer: string;
}

export interface CaseAISegmentReviewRequest {
  review_status: 'confirmed' | 'rejected' | 'inconclusive' | 'escalated';
  review_rationale: string;
  corrected_label?: string | null;
  expected_review_status?: string | null;
  expected_revision?: number | null;
  is_override?: boolean;
}

export interface CaseCreateAISegmentAnnotationRequest {
  evidence_id: string;
  start_seconds: number;
  end_seconds: number;
  raw_score: number;
  raw_label?: string;
  model_name?: string;
  model_version?: string;
  investigative_relevance?: string;
  relevance_notes?: string | null;
  calibrated_score?: number | null;
  video_duration_seconds?: number | null;
  job_id?: string | null;
}

export interface CaseAISegmentHistoryItemRead {
  event_id: string;
  timestamp: string;
  actor_id?: string | null;
  actor_role?: string | null;
  previous_review_status?: string | null;
  new_review_status: string;
  review_rationale?: string | null;
  corrected_label?: string | null;
  is_override: boolean;
  decision_revision: number;
}

// ─── Formal Case Findings (Phase 86, 116) ───────────────────────────────────

export interface CaseFindingCreate {
  finding_type: string;
  title: string;
  description: string;
  evidence_ids?: string[];
  ai_segment_ids?: string[];
  incident_ids?: string[];
  is_preliminary?: boolean;
}

export interface CaseFindingUpdate {
  expected_version_id: number;
  title?: string;
  description?: string;
  finding_type?: string;
  reason?: string;
  is_preliminary?: boolean;
  evidence_ids?: string[];
  ai_segment_ids?: string[];
  incident_ids?: string[];
  target_status?: CaseStatus;
}

export interface CaseFindingHistoryRead {
  id: string;
  finding_id: string;
  version_id: number;
  editor_id: string;
  title: string;
  description: string;
  reason?: string | null;
  created_at: string;
}
