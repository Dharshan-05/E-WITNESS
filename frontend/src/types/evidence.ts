/**
 * Digital Evidence & Legal Hold Types.
 * Matches backend `backend/app/schemas/evidence.py` and models.
 */

export type UploadStatus =
  | 'pending'
  | 'uploading'
  | 'completed'
  | 'quarantined'
  | 'failed'
  | 'rejected';

export interface EvidenceAttachment {
  id: string;
  department_id: string;
  incident_id?: string | null;
  original_filename: string;
  declared_mime_type: string;
  file_size_bytes: number;
  sha256_hash: string;
  upload_status: UploadStatus;
  uploader_id: string;
  is_quarantined: boolean;
  quarantine_reason?: string | null;
  created_at: string;
}

export interface LegalHold {
  id: string;
  hold_reference: string;
  evidence_id: string;
  case_id?: string | null;
  placed_by_id: string;
  reason: string;
  notes?: string | null;
  is_active: boolean;
  released_by_id?: string | null;
  release_reason?: string | null;
  released_at?: string | null;
  created_at: string;
}
