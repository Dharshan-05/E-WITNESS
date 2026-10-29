import React, { useState, useCallback, useRef } from 'react';
import { Upload, AlertTriangle, Video, FileText, ShieldAlert } from 'lucide-react';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import { UploadFileCard } from './UploadFileCard';
import { EvidenceAttachmentList } from './EvidenceAttachmentList';
import { StudentVideoRecorder } from '../video/StudentVideoRecorder';
import { useAuth } from '../../auth';
import {
  createUploadSession,
  completeUploadSession,
  initiateMultipartUpload,
  completeMultipartUpload,
  uploadToPresignedUrl,
} from '../../api/evidence';
import type {
  UploadFileEntry,
  EvidenceAttachmentRead,
  MultipartPartCompleteItem,
  ClientUploadState,
} from '../../types/evidence';
import {
  ALLOWED_MIME_TYPES,
  ALLOWED_EXTENSIONS_DISPLAY,
  MAX_FILE_SIZE_BYTES,
  MULTIPART_THRESHOLD_BYTES,
  DEFAULT_PART_SIZE_BYTES,
  formatFileSize,
} from '../../types/evidence';

interface EvidenceUploaderProps {
  incidentId: string;
  /** Callback when attachments change (new upload completed). */
  onAttachmentsChange?: (attachments: EvidenceAttachmentRead[]) => void;
  /** Maximum concurrent uploads. */
  maxConcurrent?: number;
  /** Disable the uploader (e.g., when incident is sealed). */
  disabled?: boolean;
}

let clientIdCounter = 0;
function generateClientId(): string {
  return `upload-${++clientIdCounter}-${Date.now()}`;
}

/**
 * Validate a file against allowed types and size limits.
 */
function validateFile(file: File): string | null {
  if (!ALLOWED_MIME_TYPES.includes(file.type) && file.type !== '') {
    return `File type "${file.type}" is not allowed. Accepted: ${ALLOWED_EXTENSIONS_DISPLAY}`;
  }
  if (file.size <= 0) {
    return 'File is empty (0 bytes).';
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `File exceeds maximum size of ${formatFileSize(MAX_FILE_SIZE_BYTES)}.`;
  }
  return null;
}

/**
 * Evidence file upload component with drag-and-drop, file validation,
 * progress tracking, retry/cancel, and both single-part and multipart
 * upload strategies.
 */
export const EvidenceUploader: React.FC<EvidenceUploaderProps> = ({
  incidentId,
  onAttachmentsChange,
  maxConcurrent = 2,
  disabled = false,
}) => {
  let isStudent = false;
  try {
    const auth = useAuth();
    isStudent = Boolean(auth.hasRole(['ROLE_STUDENT', 'student']));
  } catch {
    isStudent = false;
  }

  const [activeMode, setActiveMode] = useState<'video' | 'file'>(isStudent ? 'video' : 'file');
  const [entries, setEntries] = useState<UploadFileEntry[]>([]);
  const [completedAttachments, setCompletedAttachments] = useState<EvidenceAttachmentRead[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeUploadsRef = useRef(0);

  // ─── Entry state helpers ───────────────────────────────────────────────

  const updateEntry = useCallback(
    (clientId: string, updates: Partial<UploadFileEntry>) => {
      setEntries((prev) =>
        prev.map((e) => (e.clientId === clientId ? { ...e, ...updates } : e))
      );
    },
    []
  );

  // ─── Upload execution ─────────────────────────────────────────────────

  const executeUpload = useCallback(
    async (entry: UploadFileEntry) => {
      const { clientId, file } = entry;
      const abortController = new AbortController();
      updateEntry(clientId, { state: 'initializing', abortController });

      try {
        if (file.size <= MULTIPART_THRESHOLD_BYTES) {
          // ── Single-part upload flow ──
          updateEntry(clientId, { state: 'initializing' });
          const session = await createUploadSession(incidentId, {
            filename: file.name,
            content_type: file.type || 'application/octet-stream',
            file_size_bytes: file.size,
          });

          updateEntry(clientId, { state: 'uploading', progress: 0 });
          await uploadToPresignedUrl(
            session.upload_url,
            file,
            session.upload_headers,
            session.upload_method,
            abortController.signal,
            (loaded, total) => {
              const pct = Math.round((loaded / total) * 100);
              updateEntry(clientId, { progress: pct });
            }
          );

          updateEntry(clientId, { state: 'completing', progress: 100 });
          const attachment = await completeUploadSession(incidentId, session.session_id);

          updateEntry(clientId, {
            state: 'completed',
            progress: 100,
            attachment,
          });
          return attachment;
        } else {
          // ── Multipart upload flow ──
          updateEntry(clientId, { state: 'initializing' });
          const session = await initiateMultipartUpload(incidentId, {
            filename: file.name,
            content_type: file.type || 'application/octet-stream',
            file_size_bytes: file.size,
            part_size_bytes: DEFAULT_PART_SIZE_BYTES,
          });

          updateEntry(clientId, { state: 'uploading', progress: 0 });
          const completedParts: MultipartPartCompleteItem[] = [];
          const totalParts = session.total_parts;

          for (let i = 0; i < totalParts; i++) {
            if (abortController.signal.aborted) {
              throw new DOMException('Upload cancelled', 'AbortError');
            }

            const partInfo = session.part_urls[i];
            const start = i * session.part_size_bytes;
            const end = Math.min(start + session.part_size_bytes, file.size);
            const chunk = file.slice(start, end);

            const etag = await uploadToPresignedUrl(
              partInfo.upload_url,
              chunk,
              partInfo.headers,
              'PUT',
              abortController.signal,
              (loaded, _total) => {
                const partProgress = (i + loaded / (end - start)) / totalParts;
                const pct = Math.round(partProgress * 100);
                updateEntry(clientId, { progress: pct });
              }
            );

            completedParts.push({
              part_number: partInfo.part_number,
              etag,
            });
          }

          updateEntry(clientId, { state: 'completing', progress: 100 });
          const attachment = await completeMultipartUpload(incidentId, session.session_id, {
            parts: completedParts,
          });

          updateEntry(clientId, {
            state: 'completed',
            progress: 100,
            attachment,
          });
          return attachment;
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          updateEntry(clientId, { state: 'cancelled', error: 'Upload cancelled by user.' });
          // Best-effort abort on server for multipart
          return null;
        }
        const message = err instanceof Error ? err.message : 'Upload failed.';
        updateEntry(clientId, { state: 'failed', error: message });
        return null;
      }
    },
    [incidentId, updateEntry]
  );

  // ─── Process upload queue ──────────────────────────────────────────────

  const processQueue = useCallback(
    async (newEntries: UploadFileEntry[]) => {
      for (const entry of newEntries) {
        if (activeUploadsRef.current >= maxConcurrent) break;
        if (entry.state !== 'queued') continue;

        activeUploadsRef.current++;
        updateEntry(entry.clientId, { state: 'validating' });

        // Client-side validation
        const validationError = validateFile(entry.file);
        if (validationError) {
          updateEntry(entry.clientId, { state: 'failed', error: validationError });
          activeUploadsRef.current--;
          continue;
        }

        // Fire and manage concurrency
        executeUpload(entry).then((attachment) => {
          activeUploadsRef.current--;
          if (attachment) {
            setCompletedAttachments((prev) => {
              const next = [...prev, attachment];
              onAttachmentsChange?.(next);
              return next;
            });
          }
          // Process more queued items
          setEntries((current) => {
            const queued = current.filter((e) => e.state === 'queued');
            if (queued.length > 0) {
              processQueue(queued);
            }
            return current;
          });
        });
      }
    },
    [maxConcurrent, updateEntry, executeUpload, onAttachmentsChange]
  );

  // ─── File selection handlers ───────────────────────────────────────────

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      setValidationErrors([]);
      const fileArray = Array.from(files);
      const errors: string[] = [];
      const newEntries: UploadFileEntry[] = [];

      for (const file of fileArray) {
        const error = validateFile(file);
        if (error) {
          errors.push(`${file.name}: ${error}`);
          continue;
        }
        const entry: UploadFileEntry = {
          clientId: generateClientId(),
          file,
          state: 'queued' as ClientUploadState,
          progress: 0,
        };
        newEntries.push(entry);
      }

      if (errors.length > 0) {
        setValidationErrors(errors);
      }

      if (newEntries.length > 0) {
        setEntries((prev) => {
          const updated = [...prev, ...newEntries];
          // Start processing after state update
          setTimeout(() => processQueue(newEntries), 0);
          return updated;
        });
      }
    },
    [processQueue]
  );

  const handleFileInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      if (isStudent) {
        setValidationErrors([
          'Local disk uploads are disabled for student accounts. Please record live video directly with automated GPS & timestamp.',
        ]);
        event.target.value = '';
        return;
      }
      if (event.target.files && event.target.files.length > 0) {
        addFiles(event.target.files);
        // Reset input value so the same file can be re-selected
        event.target.value = '';
      }
    },
    [addFiles, isStudent]
  );

  // ─── Drag and drop handlers ────────────────────────────────────────────

  const handleDragOver = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (!disabled && !isStudent) setIsDragOver(true);
    },
    [disabled, isStudent]
  );

  const handleDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      event.stopPropagation();
      setIsDragOver(false);
      if (disabled) return;
      if (isStudent) {
        setValidationErrors([
          'Local disk uploads are disabled for student accounts. Please record live video directly with automated GPS & timestamp.',
        ]);
        return;
      }
      if (event.dataTransfer.files && event.dataTransfer.files.length > 0) {
        addFiles(event.dataTransfer.files);
      }
    },
    [disabled, addFiles, isStudent]
  );

  // ─── Action handlers ──────────────────────────────────────────────────

  const handleCancel = useCallback(
    (clientId: string) => {
      setEntries((prev) => {
        const entry = prev.find((e) => e.clientId === clientId);
        if (entry?.abortController) {
          entry.abortController.abort();
        }
        return prev;
      });
      // Also attempt to abort multipart on server (best-effort)
      const entry = entries.find((e) => e.clientId === clientId);
      if (entry) {
        updateEntry(clientId, { state: 'cancelled', error: 'Upload cancelled by user.' });
      }
    },
    [entries, updateEntry]
  );

  const handleRetry = useCallback(
    (clientId: string) => {
      setEntries((prev) => {
        const entry = prev.find((e) => e.clientId === clientId);
        if (entry) {
          const retryEntry: UploadFileEntry = {
            ...entry,
            state: 'queued',
            progress: 0,
            error: undefined,
            attachment: undefined,
            abortController: undefined,
          };
          const updated = prev.map((e) => (e.clientId === clientId ? retryEntry : e));
          setTimeout(() => processQueue([retryEntry]), 0);
          return updated;
        }
        return prev;
      });
    },
    [processQueue]
  );

  const handleRemove = useCallback((clientId: string) => {
    setEntries((prev) => prev.filter((e) => e.clientId !== clientId));
  }, []);

  // ─── Render ────────────────────────────────────────────────────────────

  const hasEntries = entries.length > 0;

  return (
    <div className="space-y-4" data-testid="evidence-uploader">
      {/* Validation errors */}
      {validationErrors.length > 0 && (
        <Alert variant="warning" data-testid="upload-validation-errors">
          <div className="space-y-1">
            <p className="font-medium">Some files could not be added:</p>
            <ul className="list-disc list-inside text-xs space-y-0.5">
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        </Alert>
      )}

      {/* Mode selection tabs for reviewers/investigators */}
      {!isStudent && (
        <div className="flex items-center space-x-2 border-b border-slate-200 pb-2">
          <button
            type="button"
            onClick={() => setActiveMode('file')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-1.5 transition-colors ${
              activeMode === 'file'
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            <FileText className="h-3.5 w-3.5" />
            <span>File Upload</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveMode('video')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center space-x-1.5 transition-colors ${
              activeMode === 'video'
                ? 'bg-indigo-600 text-white shadow-xs'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            <Video className="h-3.5 w-3.5" />
            <span>Record Live Video</span>
          </button>
        </div>
      )}

      {/* Student Custody Policy Alert */}
      {isStudent && (
        <div className="p-3.5 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 space-y-1">
          <div className="flex items-center gap-1.5 font-bold text-amber-950">
            <ShieldAlert className="h-4 w-4 text-amber-600" />
            <span>Student Custody Policy: Direct File Upload Prohibited</span>
          </div>
          <p>
            To prevent upload of modified, external, or pre-recorded files, students cannot upload files from disk.
            You must record live video directly via your device camera with verified GPS coordinates and hardware timestamp.
          </p>
        </div>
      )}

      {/* Live Video Capture (Always visible for students, or when toggled by reviewers) */}
      {(isStudent || activeMode === 'video') && (
        <StudentVideoRecorder
          onVideoConfirmed={(file) => {
            addFiles([file]);
          }}
        />
      )}

      {/* Hidden file input for accessibility and programmatic testing */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ALLOWED_MIME_TYPES.join(',')}
        className="sr-only"
        onChange={handleFileInputChange}
        disabled={disabled || isStudent}
        aria-label="Select evidence files to upload"
        data-testid="upload-file-input"
      />

      {/* Drop zone for non-student file uploaders */}
      {(!isStudent && activeMode === 'file') && (
        <div
          className={`
            relative border-2 border-dashed rounded-xl p-6 text-center transition-colors
            ${disabled
              ? 'border-slate-200 bg-slate-50 cursor-not-allowed opacity-60'
              : isDragOver
                ? 'border-indigo-400 bg-indigo-50/50'
                : 'border-slate-300 bg-white hover:border-indigo-300 hover:bg-slate-50/50 cursor-pointer'
            }
          `}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => !disabled && fileInputRef.current?.click()}
          role="button"
          tabIndex={disabled ? -1 : 0}
          aria-label="Drop evidence files here or click to browse"
          aria-disabled={disabled}
          onKeyDown={(e) => {
            if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
              e.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          data-testid="upload-drop-zone"
        >
          <Upload className={`h-8 w-8 mx-auto mb-2 ${isDragOver ? 'text-indigo-500' : 'text-slate-400'}`} />
          <p className="text-sm font-medium text-slate-700">
            {isDragOver ? 'Drop files to upload' : 'Drag & drop evidence files, or click to browse'}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            Max {formatFileSize(MAX_FILE_SIZE_BYTES)} per file · {ALLOWED_EXTENSIONS_DISPLAY}
          </p>
        </div>
      )}

      {/* Statutory notice */}
      <div className="flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
        <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
        <span>
          Uploaded files undergo automated malware scanning and cryptographic integrity recording.
          Evidence submission creates an immutable audit trail. Do not upload files containing
          credentials or classified information outside institutional policy.
        </span>
      </div>

      {/* File cards */}
      {hasEntries && (
        <div className="space-y-2" data-testid="upload-file-list">
          {entries.map((entry) => (
            <UploadFileCard
              key={entry.clientId}
              entry={entry}
              onCancel={handleCancel}
              onRetry={handleRetry}
              onRemove={handleRemove}
            />
          ))}
        </div>
      )}

      {/* Completed attachments summary */}
      <EvidenceAttachmentList
        attachments={completedAttachments}
        title="Uploaded Evidence"
      />

      {/* Alternative browse button */}
      {!disabled && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            aria-label="Browse for evidence files"
          >
            <Upload className="h-4 w-4 mr-1.5" />
            Add More Files
          </Button>
        </div>
      )}
    </div>
  );
};
