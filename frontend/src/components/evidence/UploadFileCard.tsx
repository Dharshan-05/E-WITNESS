import React from 'react';
import { FileText, CheckCircle2, XCircle, Loader2, X, RefreshCw } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { UploadProgressBar } from './UploadProgressBar';
import type { UploadFileEntry } from '../../types/evidence';
import { formatFileSize } from '../../types/evidence';

interface UploadFileCardProps {
  entry: UploadFileEntry;
  onCancel?: (clientId: string) => void;
  onRetry?: (clientId: string) => void;
  onRemove?: (clientId: string) => void;
}

/**
 * Individual file upload status card with progress, cancel/retry, and result display.
 */
export const UploadFileCard: React.FC<UploadFileCardProps> = ({
  entry,
  onCancel,
  onRetry,
  onRemove,
}) => {
  const isActive = ['validating', 'initializing', 'uploading', 'completing'].includes(entry.state);
  const isComplete = entry.state === 'completed';
  const isFailed = entry.state === 'failed';
  const isCancelled = entry.state === 'cancelled';

  const statusBadgeVariant: 'default' | 'primary' | 'success' | 'danger' | 'warning' =
    isComplete
      ? 'success'
      : isFailed
        ? 'danger'
        : isCancelled
          ? 'warning'
          : isActive
            ? 'primary'
            : 'default';

  const statusLabel =
    entry.state === 'queued'
      ? 'Queued'
      : entry.state === 'validating'
        ? 'Validating'
        : entry.state === 'initializing'
          ? 'Initializing'
          : entry.state === 'uploading'
            ? 'Uploading'
            : entry.state === 'completing'
              ? 'Finalizing'
              : entry.state === 'completed'
                ? 'Complete'
                : entry.state === 'failed'
                  ? 'Failed'
                  : 'Cancelled';

  const StatusIcon = isComplete
    ? CheckCircle2
    : isFailed || isCancelled
      ? XCircle
      : isActive
        ? Loader2
        : FileText;

  const iconColor = isComplete
    ? 'text-emerald-600'
    : isFailed
      ? 'text-red-600'
      : isCancelled
        ? 'text-amber-600'
        : isActive
          ? 'text-indigo-600'
          : 'text-slate-400';

  return (
    <div
      className="border border-slate-200 rounded-lg p-3 bg-white hover:border-slate-300 transition-colors"
      data-testid={`upload-file-card-${entry.clientId}`}
    >
      <div className="flex items-start gap-3">
        {/* Icon */}
        <div className={`shrink-0 mt-0.5 ${iconColor}`}>
          <StatusIcon className={`h-5 w-5 ${isActive ? 'animate-spin' : ''}`} />
        </div>

        {/* File info */}
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-900 truncate" title={entry.file.name}>
              {entry.file.name}
            </span>
            <Badge variant={statusBadgeVariant} size="sm">
              {statusLabel}
            </Badge>
          </div>

          <div className="text-xs text-slate-500">
            {formatFileSize(entry.file.size)}
            {entry.file.type && <span className="ml-2">{entry.file.type}</span>}
          </div>

          {/* Progress bar for active uploads */}
          {isActive && (
            <UploadProgressBar
              progress={entry.progress}
              filename={entry.file.name}
              statusText={statusLabel}
            />
          )}

          {/* Error message */}
          {isFailed && entry.error && (
            <p className="text-xs text-red-600 mt-1" role="alert">
              {entry.error}
            </p>
          )}

          {/* Completed attachment info */}
          {isComplete && entry.attachment && (
            <div className="text-xs text-emerald-700 bg-emerald-50 rounded px-2 py-1 mt-1">
              <span className="font-medium">Evidence ID:</span>{' '}
              <span className="font-mono">{entry.attachment.id.slice(0, 8)}…</span>
              {entry.attachment.scan_status && (
                <span className="ml-2">
                  Scan: <span className="font-medium">{entry.attachment.scan_status}</span>
                </span>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="shrink-0 flex items-center gap-1">
          {isActive && onCancel && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onCancel(entry.clientId)}
              aria-label={`Cancel upload of ${entry.file.name}`}
            >
              <X className="h-4 w-4" />
            </Button>
          )}
          {(isFailed || isCancelled) && onRetry && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRetry(entry.clientId)}
              aria-label={`Retry upload of ${entry.file.name}`}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          )}
          {(isComplete || isFailed || isCancelled) && onRemove && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemove(entry.clientId)}
              aria-label={`Remove ${entry.file.name} from list`}
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
