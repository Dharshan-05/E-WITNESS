/**
 * Administration and System Settings Types (Phase 118).
 * Aligns with backend `backend/app/schemas/admin.py`.
 */

export interface SystemSettings {
  environment: string;
  app_version: string;
  log_level: string;
  cors_allowed_origins: string[];
  auth_access_token_expire_minutes: number;
  auth_refresh_token_expire_days: number;
  biometric_matching_enabled: boolean;
  maintenance_mode: boolean;
  system_announcement?: string | null;
  database_status: string;
  redis_status: string;
  storage_endpoint_url_redacted: string;
  storage_bucket_name: string;
  storage_region: string;
  ai_provider: string;
  max_upload_size_bytes: number;
  allowed_evidence_mime_types: string[];
}

export interface SystemSettingsUpdate {
  maintenance_mode?: boolean;
  system_announcement?: string | null;
}

export interface DepartmentSettings {
  department_id: string;
  code: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  contact_email?: string | null;
  retention_period_days: number;
  max_active_cases_per_investigator: number;
  require_two_party_case_closure: boolean;
}

export interface DepartmentSettingsUpdate {
  description?: string | null;
  contact_email?: string | null;
  retention_period_days?: number;
  max_active_cases_per_investigator?: number;
  require_two_party_case_closure?: boolean;
}

export interface DepartmentListItem {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  created_at?: string | null;
}
