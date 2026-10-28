import { apiClient } from './client';
import type {
  UploadSessionCreateRequest,
  UploadSessionResponse,
  MultipartUploadInitRequest,
  MultipartUploadInitResponse,
  MultipartUploadCompleteRequest,
  EvidenceAttachmentRead,
  EvidenceDownloadResponse,
} from '../types/evidence';

// ─── Evidence API Client ───────────────────────────────────────────────────

/**
 * Create a single-part evidence upload session.
 * POST /incidents/{incidentId}/attachments/upload-session
 */
export async function createUploadSession(
  incidentId: string,
  payload: UploadSessionCreateRequest
): Promise<UploadSessionResponse> {
  return apiClient.post<UploadSessionResponse>(
    `/incidents/${encodeURIComponent(incidentId)}/attachments/upload-session`,
    payload
  );
}

/**
 * Get the current status of an upload session.
 * GET /incidents/attachments/upload-sessions/{sessionId}
 */
export async function getUploadSessionStatus(
  sessionId: string
): Promise<UploadSessionResponse> {
  return apiClient.get<UploadSessionResponse>(
    `/incidents/attachments/upload-sessions/${encodeURIComponent(sessionId)}`
  );
}

/**
 * Complete a single-part upload session (verify, scan, attach).
 * POST /incidents/{incidentId}/attachments/upload-sessions/{sessionId}/complete
 */
export async function completeUploadSession(
  incidentId: string,
  sessionId: string
): Promise<EvidenceAttachmentRead> {
  return apiClient.post<EvidenceAttachmentRead>(
    `/incidents/${encodeURIComponent(incidentId)}/attachments/upload-sessions/${encodeURIComponent(sessionId)}/complete`
  );
}

/**
 * Initiate a multipart (chunked) evidence upload session.
 * POST /incidents/{incidentId}/attachments/multipart/init
 */
export async function initiateMultipartUpload(
  incidentId: string,
  payload: MultipartUploadInitRequest
): Promise<MultipartUploadInitResponse> {
  return apiClient.post<MultipartUploadInitResponse>(
    `/incidents/${encodeURIComponent(incidentId)}/attachments/multipart/init`,
    payload
  );
}

/**
 * Complete a multipart upload session (assemble, verify, scan, attach).
 * POST /incidents/{incidentId}/attachments/multipart/{sessionId}/complete
 */
export async function completeMultipartUpload(
  incidentId: string,
  sessionId: string,
  payload: MultipartUploadCompleteRequest
): Promise<EvidenceAttachmentRead> {
  return apiClient.post<EvidenceAttachmentRead>(
    `/incidents/${encodeURIComponent(incidentId)}/attachments/multipart/${encodeURIComponent(sessionId)}/complete`,
    payload
  );
}

/**
 * Abort a multipart upload session and clean up allocated storage.
 * POST /incidents/{incidentId}/attachments/multipart/{sessionId}/abort
 */
export async function abortMultipartUpload(
  incidentId: string,
  sessionId: string
): Promise<void> {
  await apiClient.post(
    `/incidents/${encodeURIComponent(incidentId)}/attachments/multipart/${encodeURIComponent(sessionId)}/abort`
  );
}

/**
 * List evidence attachments for an incident.
 * GET /incidents/{incidentId}/attachments
 */
export async function listAttachments(
  incidentId: string
): Promise<EvidenceAttachmentRead[]> {
  return apiClient.get<EvidenceAttachmentRead[]>(
    `/incidents/${encodeURIComponent(incidentId)}/attachments`
  );
}

/**
 * Get evidence attachment metadata.
 * GET /incidents/{incidentId}/attachments/{attachmentId}
 */
export async function getAttachment(
  incidentId: string,
  attachmentId: string
): Promise<EvidenceAttachmentRead> {
  return apiClient.get<EvidenceAttachmentRead>(
    `/incidents/${encodeURIComponent(incidentId)}/attachments/${encodeURIComponent(attachmentId)}`
  );
}

/**
 * Generate authorized short-lived pre-signed download URL for evidence.
 * GET /incidents/{incidentId}/attachments/{attachmentId}/download
 */
export async function getAttachmentDownloadUrl(
  incidentId: string,
  attachmentId: string,
  expiresInSeconds: number = 300
): Promise<EvidenceDownloadResponse> {
  return apiClient.get<EvidenceDownloadResponse>(
    `/incidents/${encodeURIComponent(incidentId)}/attachments/${encodeURIComponent(attachmentId)}/download`,
    { params: { expires_in_seconds: expiresInSeconds } }
  );
}

/**
 * Upload a file blob directly to a pre-signed URL (outside the API).
 * Returns the ETag header from the storage provider response.
 */
export async function uploadToPresignedUrl(
  url: string,
  blob: Blob,
  headers: Record<string, string>,
  method: string = 'PUT',
  signal?: AbortSignal,
  onProgress?: (loaded: number, total: number) => void
): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url);

    for (const [key, value] of Object.entries(headers)) {
      xhr.setRequestHeader(key, value);
    }

    if (signal) {
      signal.addEventListener('abort', () => {
        xhr.abort();
        reject(new DOMException('Upload cancelled', 'AbortError'));
      });
    }

    if (onProgress) {
      xhr.upload.addEventListener('progress', (event) => {
        if (event.lengthComputable) {
          onProgress(event.loaded, event.total);
        }
      });
    }

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const etag = xhr.getResponseHeader('ETag') || '';
        resolve(etag);
      } else {
        reject(new Error(`Upload failed with status ${xhr.status}: ${xhr.statusText}`));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new Error('Network error during upload'));
    });

    xhr.addEventListener('abort', () => {
      reject(new DOMException('Upload cancelled', 'AbortError'));
    });

    xhr.send(blob);
  });
}
