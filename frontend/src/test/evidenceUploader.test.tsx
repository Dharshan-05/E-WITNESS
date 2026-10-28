import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EvidenceUploader } from '../components/evidence/EvidenceUploader';
import { UploadProgressBar } from '../components/evidence/UploadProgressBar';
import { EvidenceAttachmentList } from '../components/evidence/EvidenceAttachmentList';
import * as evidenceApi from '../api/evidence';
import type {
  UploadSessionResponse,
  MultipartUploadInitResponse,
  EvidenceAttachmentRead,
} from '../types/evidence';

describe('EvidenceUploader Component', () => {
  const incidentId = '11111111-1111-1111-1111-111111111111';

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders drop zone, notice, and file input with correct accessibility attributes', () => {
    render(<EvidenceUploader incidentId={incidentId} />);

    expect(screen.getByTestId('upload-drop-zone')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /drop evidence files here/i })).toBeInTheDocument();
    expect(
      screen.getByText(/drag & drop evidence files, or click to browse/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/automated malware scanning/i)).toBeInTheDocument();

    const input = screen.getByTestId('upload-file-input') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.type).toBe('file');
    expect(input.multiple).toBe(true);
  });

  it('validates and rejects disallowed file types', async () => {
    render(<EvidenceUploader incidentId={incidentId} />);

    const disallowedFile = new File(['executable content'], 'virus.exe', {
      type: 'application/x-msdownload',
    });

    const input = screen.getByTestId('upload-file-input');
    fireEvent.change(input, { target: { files: [disallowedFile] } });

    await waitFor(() => {
      expect(screen.getByTestId('upload-validation-errors')).toBeInTheDocument();
      expect(
        screen.getByText(/File type "application\/x-msdownload" is not allowed/i)
      ).toBeInTheDocument();
    });
  });

  it('validates and rejects empty (0-byte) files', async () => {
    render(<EvidenceUploader incidentId={incidentId} />);

    const emptyFile = new File([], 'empty.png', { type: 'image/png' });

    const input = screen.getByTestId('upload-file-input');
    fireEvent.change(input, { target: { files: [emptyFile] } });

    await waitFor(() => {
      expect(screen.getByTestId('upload-validation-errors')).toBeInTheDocument();
      expect(screen.getByText(/File is empty \(0 bytes\)/i)).toBeInTheDocument();
    });
  });

  it('executes single-part upload lifecycle for small files (<= 10MB)', async () => {
    const mockSession: UploadSessionResponse = {
      session_id: 'session-123',
      incident_id: incidentId,
      storage_key: 'incidents/photo.png',
      original_filename: 'photo.png',
      expected_size_bytes: 5000,
      upload_url: 'https://storage/upload-presigned',
      upload_method: 'PUT',
      upload_headers: { 'Content-Type': 'image/png' },
      expires_at: '2026-10-28T23:59:59Z',
      session_status: 'active',
    };

    const mockAttachment: EvidenceAttachmentRead = {
      id: 'att-999',
      incident_id: incidentId,
      uploader_id: 'user-1',
      department_id: 'dept-1',
      original_filename: 'photo.png',
      declared_mime_type: 'image/png',
      detected_mime_type: 'image/png',
      file_size_bytes: 5000,
      sha256_hash: 'c'.repeat(64),
      upload_status: 'completed',
      evidence_status: 'attached',
      scan_status: 'clean',
      scanned_at: '2026-10-28T23:00:00Z',
      scan_details: 'Clean',
      ingested_at: '2026-10-28T23:00:00Z',
      client_reported_at: null,
      uploader_ip: '127.0.0.1',
      user_agent: 'Test',
      created_at: '2026-10-28T23:00:00Z',
      updated_at: '2026-10-28T23:00:00Z',
    };

    const createSessionSpy = vi
      .spyOn(evidenceApi, 'createUploadSession')
      .mockResolvedValue(mockSession);
    const presignedSpy = vi
      .spyOn(evidenceApi, 'uploadToPresignedUrl')
      .mockResolvedValue('"etag-123"');
    const completeSessionSpy = vi
      .spyOn(evidenceApi, 'completeUploadSession')
      .mockResolvedValue(mockAttachment);

    const onAttachmentsChange = vi.fn();

    render(
      <EvidenceUploader
        incidentId={incidentId}
        onAttachmentsChange={onAttachmentsChange}
      />
    );

    const validFile = new File(['valid image binary bytes'], 'photo.png', {
      type: 'image/png',
    });

    const input = screen.getByTestId('upload-file-input');
    fireEvent.change(input, { target: { files: [validFile] } });

    await waitFor(() => {
      expect(createSessionSpy).toHaveBeenCalledWith(
        incidentId,
        expect.objectContaining({
          filename: 'photo.png',
          content_type: 'image/png',
        })
      );
      expect(presignedSpy).toHaveBeenCalledWith(
        mockSession.upload_url,
        validFile,
        mockSession.upload_headers,
        'PUT',
        expect.any(AbortSignal),
        expect.any(Function)
      );
      expect(completeSessionSpy).toHaveBeenCalledWith(incidentId, 'session-123');
      expect(onAttachmentsChange).toHaveBeenCalled();
    });

    // Verify UI reflects completed state
    await waitFor(() => {
      expect(screen.getByText('Complete')).toBeInTheDocument();
      expect(screen.getByText(/Evidence ID:/i)).toBeInTheDocument();
    });
  });

  it('executes multipart upload lifecycle for large files (> 10MB)', async () => {
    const mockMultipartInit: MultipartUploadInitResponse = {
      session_id: 'mp-session-456',
      incident_id: incidentId,
      storage_key: 'incidents/large_cctv.mp4',
      upload_id: 'upload-id-789',
      original_filename: 'large_cctv.mp4',
      expected_size_bytes: 15 * 1024 * 1024,
      part_size_bytes: 5 * 1024 * 1024,
      total_parts: 3,
      part_urls: [
        { part_number: 1, upload_url: 'https://storage/chunk1', headers: {} },
        { part_number: 2, upload_url: 'https://storage/chunk2', headers: {} },
        { part_number: 3, upload_url: 'https://storage/chunk3', headers: {} },
      ],
      expires_at: '2026-10-28T23:59:59Z',
      session_status: 'active',
    };

    const mockAttachment: EvidenceAttachmentRead = {
      id: 'att-large-888',
      incident_id: incidentId,
      uploader_id: 'user-1',
      department_id: 'dept-1',
      original_filename: 'large_cctv.mp4',
      declared_mime_type: 'video/mp4',
      detected_mime_type: 'video/mp4',
      file_size_bytes: 15 * 1024 * 1024,
      sha256_hash: 'd'.repeat(64),
      upload_status: 'completed',
      evidence_status: 'attached',
      scan_status: 'clean',
      scanned_at: '2026-10-28T23:00:00Z',
      scan_details: 'Clean',
      ingested_at: '2026-10-28T23:00:00Z',
      client_reported_at: null,
      uploader_ip: '127.0.0.1',
      user_agent: 'Test',
      created_at: '2026-10-28T23:00:00Z',
      updated_at: '2026-10-28T23:00:00Z',
    };

    const initSpy = vi
      .spyOn(evidenceApi, 'initiateMultipartUpload')
      .mockResolvedValue(mockMultipartInit);
    const presignedSpy = vi
      .spyOn(evidenceApi, 'uploadToPresignedUrl')
      .mockResolvedValue('"etag-chunk"');
    const completeMultipartSpy = vi
      .spyOn(evidenceApi, 'completeMultipartUpload')
      .mockResolvedValue(mockAttachment);

    render(<EvidenceUploader incidentId={incidentId} />);

    // Create a mock large file (>10MB)
    const largeFile = new File([''], 'large_cctv.mp4', { type: 'video/mp4' });
    Object.defineProperty(largeFile, 'size', { value: 15 * 1024 * 1024 });

    const input = screen.getByTestId('upload-file-input');
    fireEvent.change(input, { target: { files: [largeFile] } });

    await waitFor(() => {
      expect(initSpy).toHaveBeenCalledWith(
        incidentId,
        expect.objectContaining({
          filename: 'large_cctv.mp4',
          content_type: 'video/mp4',
          file_size_bytes: 15 * 1024 * 1024,
        })
      );
      // All 3 parts uploaded
      expect(presignedSpy).toHaveBeenCalledTimes(3);
      expect(completeMultipartSpy).toHaveBeenCalledWith(
        incidentId,
        'mp-session-456',
        expect.objectContaining({
          parts: [
            { part_number: 1, etag: '"etag-chunk"' },
            { part_number: 2, etag: '"etag-chunk"' },
            { part_number: 3, etag: '"etag-chunk"' },
          ],
        })
      );
    });
  });

  it('handles upload failure gracefully and allows retry', async () => {
    vi.spyOn(evidenceApi, 'createUploadSession').mockRejectedValueOnce(
      new Error('Quota limit exceeded for department')
    );

    render(<EvidenceUploader incidentId={incidentId} />);

    const file = new File(['some bytes'], 'notes.pdf', { type: 'application/pdf' });
    const input = screen.getByTestId('upload-file-input');
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('Failed')).toBeInTheDocument();
      expect(screen.getByText(/Quota limit exceeded/i)).toBeInTheDocument();
    });

    // Verify retry button is rendered
    const retryBtn = screen.getByRole('button', { name: /retry upload/i });
    expect(retryBtn).toBeInTheDocument();
  });

  it('respects disabled prop and disables interaction', () => {
    render(<EvidenceUploader incidentId={incidentId} disabled={true} />);

    const dropZone = screen.getByTestId('upload-drop-zone');
    expect(dropZone).toHaveAttribute('aria-disabled', 'true');

    const input = screen.getByTestId('upload-file-input');
    expect(input).toBeDisabled();

    // "Add More Files" button should not be rendered when disabled
    expect(screen.queryByRole('button', { name: /add more files/i })).not.toBeInTheDocument();
  });
});

describe('UploadProgressBar Component', () => {
  it('renders progress bar with ARIA accessibility roles and values', () => {
    render(
      <UploadProgressBar
        progress={65}
        filename="security_video.mp4"
        statusText="Streaming chunks…"
      />
    );

    const progressBar = screen.getByRole('progressbar');
    expect(progressBar).toBeInTheDocument();
    expect(progressBar).toHaveAttribute('aria-valuenow', '65');
    expect(progressBar).toHaveAttribute('aria-valuemin', '0');
    expect(progressBar).toHaveAttribute('aria-valuemax', '100');
    expect(progressBar).toHaveAttribute(
      'aria-label',
      'Upload progress for security_video.mp4'
    );
    expect(screen.getByText('65%')).toBeInTheDocument();
    expect(screen.getByText('Streaming chunks…')).toBeInTheDocument();
  });

  it('clamps progress between 0 and 100', () => {
    const { rerender } = render(
      <UploadProgressBar progress={-10} filename="test.png" />
    );
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');

    rerender(<UploadProgressBar progress={150} filename="test.png" />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  });
});

describe('EvidenceAttachmentList Component', () => {
  it('renders attachments with sanitized filenames and SHA-256 digests', () => {
    const attachments: EvidenceAttachmentRead[] = [
      {
        id: '12345678-1234-1234-1234-1234567890ab',
        incident_id: 'incident-1',
        uploader_id: 'user-1',
        department_id: 'dept-1',
        original_filename: 'surveillance_capture.png',
        declared_mime_type: 'image/png',
        detected_mime_type: 'image/png',
        file_size_bytes: 2048576,
        sha256_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        upload_status: 'completed',
        evidence_status: 'attached',
        scan_status: 'clean',
        scanned_at: '2026-10-28T22:00:00Z',
        scan_details: 'Clean',
        ingested_at: '2026-10-28T22:00:00Z',
        client_reported_at: null,
        uploader_ip: '192.168.1.1',
        user_agent: 'Browser',
        created_at: '2026-10-28T22:00:00Z',
        updated_at: '2026-10-28T22:00:00Z',
      },
    ];

    render(<EvidenceAttachmentList attachments={attachments} />);

    expect(screen.getByText('surveillance_capture.png')).toBeInTheDocument();
    expect(screen.getByText('clean')).toBeInTheDocument();
    expect(screen.getByText(/SHA-256:/i)).toBeInTheDocument();
  });

  it('renders nothing when attachment array is empty', () => {
    const { container } = render(<EvidenceAttachmentList attachments={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
