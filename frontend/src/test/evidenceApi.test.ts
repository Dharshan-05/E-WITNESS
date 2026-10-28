import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  createUploadSession,
  getUploadSessionStatus,
  completeUploadSession,
  initiateMultipartUpload,
  completeMultipartUpload,
  abortMultipartUpload,
  listAttachments,
  getAttachment,
  uploadToPresignedUrl,
} from '../api/evidence';
import { apiClient } from '../api/client';
import type {
  UploadSessionResponse,
  MultipartUploadInitResponse,
  EvidenceAttachmentRead,
} from '../types/evidence';

describe('Evidence API Client', () => {
  const incidentId = '11111111-1111-1111-1111-111111111111';
  const sessionId = '22222222-2222-2222-2222-222222222222';
  const attachmentId = '33333333-3333-3333-3333-333333333333';

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('createUploadSession posts to the single-part upload session endpoint', async () => {
    const mockResponse: UploadSessionResponse = {
      session_id: sessionId,
      incident_id: incidentId,
      storage_key: 'incidents/key.png',
      original_filename: 'evidence.png',
      expected_size_bytes: 1024,
      upload_url: 'https://storage.example.com/upload',
      upload_method: 'PUT',
      upload_headers: { 'Content-Type': 'image/png' },
      expires_at: '2026-10-28T23:59:59Z',
      session_status: 'active',
    };

    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockResponse);

    const payload = {
      filename: 'evidence.png',
      content_type: 'image/png',
      file_size_bytes: 1024,
    };

    const result = await createUploadSession(incidentId, payload);
    expect(postSpy).toHaveBeenCalledWith(
      `/incidents/${incidentId}/attachments/upload-session`,
      payload
    );
    expect(result).toEqual(mockResponse);
  });

  it('getUploadSessionStatus fetches the session status endpoint', async () => {
    const mockResponse: UploadSessionResponse = {
      session_id: sessionId,
      incident_id: incidentId,
      storage_key: 'incidents/key.png',
      original_filename: 'evidence.png',
      expected_size_bytes: 1024,
      upload_url: 'https://storage.example.com/upload',
      upload_method: 'PUT',
      upload_headers: {},
      expires_at: '2026-10-28T23:59:59Z',
      session_status: 'active',
    };

    const getSpy = vi.spyOn(apiClient, 'get').mockResolvedValue(mockResponse);

    const result = await getUploadSessionStatus(sessionId);
    expect(getSpy).toHaveBeenCalledWith(`/incidents/attachments/upload-sessions/${sessionId}`);
    expect(result).toEqual(mockResponse);
  });

  it('completeUploadSession completes single-part upload', async () => {
    const mockAttachment: EvidenceAttachmentRead = {
      id: attachmentId,
      incident_id: incidentId,
      uploader_id: '44444444-4444-4444-4444-444444444444',
      department_id: '55555555-5555-5555-5555-555555555555',
      original_filename: 'evidence.png',
      declared_mime_type: 'image/png',
      detected_mime_type: 'image/png',
      file_size_bytes: 1024,
      sha256_hash: 'a'.repeat(64),
      upload_status: 'completed',
      evidence_status: 'attached',
      scan_status: 'clean',
      scanned_at: '2026-10-28T23:00:00Z',
      scan_details: 'Clean',
      ingested_at: '2026-10-28T23:00:00Z',
      client_reported_at: null,
      uploader_ip: '127.0.0.1',
      user_agent: 'Vitest/Test',
      created_at: '2026-10-28T23:00:00Z',
      updated_at: '2026-10-28T23:00:00Z',
    };

    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockAttachment);

    const result = await completeUploadSession(incidentId, sessionId);
    expect(postSpy).toHaveBeenCalledWith(
      `/incidents/${incidentId}/attachments/upload-sessions/${sessionId}/complete`
    );
    expect(result).toEqual(mockAttachment);
  });

  it('initiateMultipartUpload posts to multipart init endpoint', async () => {
    const mockResponse: MultipartUploadInitResponse = {
      session_id: sessionId,
      incident_id: incidentId,
      storage_key: 'incidents/multipart.mp4',
      upload_id: 'mp-upload-123',
      original_filename: 'video.mp4',
      expected_size_bytes: 20 * 1024 * 1024,
      part_size_bytes: 5 * 1024 * 1024,
      total_parts: 4,
      part_urls: [
        { part_number: 1, upload_url: 'https://storage/part1', headers: {} },
        { part_number: 2, upload_url: 'https://storage/part2', headers: {} },
        { part_number: 3, upload_url: 'https://storage/part3', headers: {} },
        { part_number: 4, upload_url: 'https://storage/part4', headers: {} },
      ],
      expires_at: '2026-10-28T23:59:59Z',
      session_status: 'active',
    };

    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockResponse);

    const payload = {
      filename: 'video.mp4',
      content_type: 'video/mp4',
      file_size_bytes: 20 * 1024 * 1024,
      part_size_bytes: 5 * 1024 * 1024,
    };

    const result = await initiateMultipartUpload(incidentId, payload);
    expect(postSpy).toHaveBeenCalledWith(
      `/incidents/${incidentId}/attachments/multipart/init`,
      payload
    );
    expect(result).toEqual(mockResponse);
  });

  it('completeMultipartUpload posts completed parts array', async () => {
    const mockAttachment: EvidenceAttachmentRead = {
      id: attachmentId,
      incident_id: incidentId,
      uploader_id: 'user-1',
      department_id: 'dept-1',
      original_filename: 'video.mp4',
      declared_mime_type: 'video/mp4',
      detected_mime_type: 'video/mp4',
      file_size_bytes: 20 * 1024 * 1024,
      sha256_hash: 'b'.repeat(64),
      upload_status: 'completed',
      evidence_status: 'attached',
      scan_status: 'clean',
      scanned_at: '2026-10-28T23:00:00Z',
      scan_details: 'Clean',
      ingested_at: '2026-10-28T23:00:00Z',
      client_reported_at: null,
      uploader_ip: '127.0.0.1',
      user_agent: 'Vitest/Test',
      created_at: '2026-10-28T23:00:00Z',
      updated_at: '2026-10-28T23:00:00Z',
    };

    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue(mockAttachment);

    const payload = {
      parts: [
        { part_number: 1, etag: '"etag-1"' },
        { part_number: 2, etag: '"etag-2"' },
      ],
    };

    const result = await completeMultipartUpload(incidentId, sessionId, payload);
    expect(postSpy).toHaveBeenCalledWith(
      `/incidents/${incidentId}/attachments/multipart/${sessionId}/complete`,
      payload
    );
    expect(result).toEqual(mockAttachment);
  });

  it('abortMultipartUpload posts to multipart abort endpoint', async () => {
    const postSpy = vi.spyOn(apiClient, 'post').mockResolvedValue({});

    await abortMultipartUpload(incidentId, sessionId);
    expect(postSpy).toHaveBeenCalledWith(
      `/incidents/${incidentId}/attachments/multipart/${sessionId}/abort`
    );
  });

  it('listAttachments and getAttachment call appropriate GET endpoints', async () => {
    const listSpy = vi.spyOn(apiClient, 'get').mockResolvedValue([]);
    await listAttachments(incidentId);
    expect(listSpy).toHaveBeenCalledWith(`/incidents/${incidentId}/attachments`);

    const singleSpy = vi.spyOn(apiClient, 'get').mockResolvedValue({ id: attachmentId });
    await getAttachment(incidentId, attachmentId);
    expect(singleSpy).toHaveBeenCalledWith(
      `/incidents/${incidentId}/attachments/${attachmentId}`
    );
  });

  describe('uploadToPresignedUrl', () => {
    it('uploads blob via XMLHttpRequest and resolves with ETag header', async () => {
      const mockXHR = {
        open: vi.fn(),
        setRequestHeader: vi.fn(),
        send: vi.fn(),
        abort: vi.fn(),
        status: 200,
        statusText: 'OK',
        getResponseHeader: vi.fn().mockReturnValue('"etag-abc-123"'),
        upload: {
          addEventListener: vi.fn(),
        },
        addEventListener: vi.fn((event: string, callback: () => void) => {
          if (event === 'load') {
            setTimeout(callback, 0);
          }
        }),
      };

      vi.stubGlobal('XMLHttpRequest', vi.fn(() => mockXHR));

      const blob = new Blob(['sample data'], { type: 'text/plain' });
      const etag = await uploadToPresignedUrl(
        'https://storage.example.com/put-object',
        blob,
        { 'Content-Type': 'text/plain' },
        'PUT'
      );

      expect(mockXHR.open).toHaveBeenCalledWith('PUT', 'https://storage.example.com/put-object');
      expect(mockXHR.setRequestHeader).toHaveBeenCalledWith('Content-Type', 'text/plain');
      expect(mockXHR.send).toHaveBeenCalledWith(blob);
      expect(etag).toBe('"etag-abc-123"');

      vi.unstubAllGlobals();
    });

    it('rejects on XMLHttpRequest HTTP error status', async () => {
      const mockXHR = {
        open: vi.fn(),
        setRequestHeader: vi.fn(),
        send: vi.fn(),
        abort: vi.fn(),
        status: 403,
        statusText: 'Forbidden',
        getResponseHeader: vi.fn().mockReturnValue(null),
        upload: { addEventListener: vi.fn() },
        addEventListener: vi.fn((event: string, callback: () => void) => {
          if (event === 'load') {
            setTimeout(callback, 0);
          }
        }),
      };

      vi.stubGlobal('XMLHttpRequest', vi.fn(() => mockXHR));

      const blob = new Blob(['sample data'], { type: 'text/plain' });
      await expect(
        uploadToPresignedUrl('https://storage.example.com/put-object', blob, {})
      ).rejects.toThrow('Upload failed with status 403: Forbidden');

      vi.unstubAllGlobals();
    });
  });
});
