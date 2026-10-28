/**
 * Investigation Case Management Types.
 * Matches backend `backend/app/schemas/case.py` and core domain models.
 */

export type CaseStatus =
  | 'draft'
  | 'open'
  | 'under_investigation'
  | 'pending_review'
  | 'pending_supervisor_review'
  | 'closed'
  | 'resolved'
  | 'reopened'
  | 'archived';

export type CasePriority = 'low' | 'medium' | 'high' | 'critical';

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

export interface Case {
  id: string;
  reference_number: string;
  title: string;
  summary: string;
  status: CaseStatus;
  priority: CasePriority;
  department_id: string;
  lead_investigator_id?: string | null;
  incident_id?: string | null;
  is_legal_hold: boolean;
  version_id: number;
  closed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseNote {
  id: string;
  case_id: string;
  author_id: string;
  visibility: CaseNoteVisibility;
  content: string;
  version_id: number;
  is_archived: boolean;
  evidence_reference_ids?: string[];
  created_at: string;
  updated_at: string;
}

export interface CaseFinding {
  id: string;
  case_id: string;
  finding_type: CaseFindingType;
  title: string;
  description: string;
  is_preliminary: boolean;
  created_at: string;
  updated_at: string;
}

export interface CaseExport {
  id: string;
  case_id: string;
  department_id: string;
  exported_by_id: string;
  export_scope: CaseExportScope;
  export_format: CaseExportFormat;
  manifest_sha256: string;
  evidence_count: number;
  manifest_payload: Record<string, unknown>;
  status: string;
  purpose: string;
  expires_at: string;
  created_at: string;
}

export interface CaseTimelineEvent {
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
