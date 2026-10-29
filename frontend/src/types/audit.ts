/**
 * Security Audit and Ledger Traceability Types (Phase 118).
 * Aligns with backend `backend/app/schemas/audit.py`.
 */

export interface SecurityAuditEvent {
  id: string;
  sequence_number: number;
  action: string;
  actor_id?: string | null;
  actor_role?: string | null;
  actor_ip?: string | null;
  actor_user_agent?: string | null;
  department_id?: string | null;
  target_type: string;
  target_id: string;
  outcome: 'success' | 'failure' | 'denied' | string;
  details?: Record<string, unknown> | null;
  previous_event_hash?: string | null;
  event_hash: string;
  created_at: string;
}

export interface AuditSearchFilterParams {
  actor_id?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  department_id?: string;
  outcome?: string;
  start_time?: string;
  end_time?: string;
  page?: number;
  page_size?: number;
}

export interface AuditVerificationReport {
  status: 'verified' | 'compromised' | 'empty' | string;
  chain_valid: boolean;
  total_events_verified: number;
  first_sequence_number?: number | null;
  last_sequence_number?: number | null;
  tampered_event_ids: string[];
  tampered_sequence_numbers: number[];
  errors: string[];
  disclaimer: string;
  verified_at: string;
}

export interface AuditEventExportRequest {
  actor_id?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  department_id?: string;
  outcome?: string;
  start_time?: string;
  end_time?: string;
  export_format?: 'json' | 'csv';
  limit?: number;
}

export interface AuditEventExportResponse {
  export_id: string;
  exported_at: string;
  export_format: string;
  total_records: number;
  content: string;
  hash_digest: string;
}
