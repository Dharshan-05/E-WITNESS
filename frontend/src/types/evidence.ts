/**
 * Digital Evidence Upload & Attachment Types — Phase 114.
 * Mirrors backend `backend/app/schemas/evidence.py` and `backend/app/core/evidence.py`.
 */

// ─── Upload lifecycle enums ────────────────────────────────────────────────

export type UploadStatus = 'pending' | 'completed' | 'failed' | 'cancelled';
export type EvidenceStatus = 'attached' | 'quarantined' | 'sealed';
export type UploadSessionStatus = 'active' | 'completed' | 'expired' | 'cancelled';
export type ScanStatus = 'pending' | 'scanning' | 'clean' | 'infected' | 'failed' | 'quarantined';

// ─── Single-part upload session ────────────────────────────────────────────

export interface UploadSessionCreateRequest {
  filename: string;
  content_type: string;
  file_size_bytes: number;
  client_reported_at?: string | null;
}

export interface UploadSessionResponse {
  session_id: string;
  incident_id: string;
  storage_key: string;
  original_filename: string;
  expected_size_bytes: number;
  upload_url: string;
  upload_method: string;
  upload_headers: Record<string, string>;
  expires_at: string;
  session_status: string;
}

// ─── Multipart (chunked) upload session ────────────────────────────────────

export interface MultipartUploadInitRequest {
  filename: string;
  content_type: string;
  file_size_bytes: number;
  part_size_bytes?: number;
  client_reported_at?: string | null;
}

export interface MultipartPartUrl {
  part_number: number;
  upload_url: string;
  headers: Record<string, string>;
}

export interface MultipartUploadInitResponse {
  session_id: string;
  incident_id: string;
  storage_key: string;
  upload_id: string;
  original_filename: string;
  expected_size_bytes: number;
  part_size_bytes: number;
  total_parts: number;
  part_urls: MultipartPartUrl[];
  expires_at: string;
  session_status: string;
}

export interface MultipartPartCompleteItem {
  part_number: number;
  etag: string;
}

export interface MultipartUploadCompleteRequest {
  parts: MultipartPartCompleteItem[];
}

// ─── Evidence attachment read model ────────────────────────────────────────

export interface EvidenceAttachmentRead {
  id: string;
  incident_id: string;
  uploader_id: string;
  department_id: string;
  original_filename: string;
  declared_mime_type: string;
  detected_mime_type: string | null;
  file_size_bytes: number;
  sha256_hash: string | null;
  upload_status: UploadStatus;
  evidence_status: EvidenceStatus;
  scan_status: ScanStatus;
  scanned_at: string | null;
  scan_details: string | null;
  ingested_at: string | null;
  client_reported_at: string | null;
  uploader_ip: string | null;
  user_agent: string | null;
  created_at: string;
  updated_at: string;
}

// ─── Legacy compat ─────────────────────────────────────────────────────────
// (Phase 111 exported these types; keep for backwards compat but prefer the
//  richer types above for Phase 114.)

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

// ─── Client-side upload tracking ───────────────────────────────────────────

export type ClientUploadState =
  | 'queued'
  | 'validating'
  | 'initializing'
  | 'uploading'
  | 'completing'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface UploadFileEntry {
  /** Client-side tracking ID */
  clientId: string;
  /** Original File object */
  file: File;
  /** Current upload lifecycle state */
  state: ClientUploadState;
  /** Upload progress 0-100 */
  progress: number;
  /** Error message if failed */
  error?: string;
  /** Server-returned attachment after completion */
  attachment?: EvidenceAttachmentRead;
  /** Abort controller for cancellation */
  abortController?: AbortController;
}

// ─── Domain constants (mirrors backend/app/core/evidence.py) ───────────────

/** Minimum chunk size for S3 multipart upload (5 MB). */
export const MIN_PART_SIZE_BYTES = 5 * 1024 * 1024;

/** Default chunk size for multipart uploads (5 MB). */
export const DEFAULT_PART_SIZE_BYTES = 5 * 1024 * 1024;

/** Maximum chunk size for multipart uploads (50 MB). */
export const MAX_PART_SIZE_BYTES = 50 * 1024 * 1024;

/** Threshold above which multipart upload is used instead of single-part. */
export const MULTIPART_THRESHOLD_BYTES = 10 * 1024 * 1024;

/** Maximum individual file size for evidence upload (250 MB). */
export const MAX_FILE_SIZE_BYTES = 250 * 1024 * 1024;

/** Allowed MIME types for evidence upload (institutional policy). */
export const ALLOWED_MIME_TYPES: readonly string[] = [
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'image/tiff',
  'video/mp4',
  'video/quicktime',
  'video/x-msvideo',
  'video/webm',
  'audio/mpeg',
  'audio/wav',
  'audio/ogg',
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/plain',
  'text/csv',
] as const;

/** Human-readable allowed file extensions for display. */
export const ALLOWED_EXTENSIONS_DISPLAY =
  'JPEG, PNG, GIF, WebP, TIFF, MP4, MOV, AVI, WebM, MP3, WAV, OGG, PDF, DOC, DOCX, XLS, XLSX, TXT, CSV';

// ─── Evidence Download (Phase 116) ─────────────────────────────────────────

export interface EvidenceDownloadResponse {
  download_url: string;
  filename: string;
  content_type: string;
  file_size_bytes: number;
  expires_at: string;
}

/**
 * Format a byte count to a human-readable string.
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exp;
  return `${value.toFixed(exp > 0 ? 1 : 0)} ${units[exp]}`;
}
