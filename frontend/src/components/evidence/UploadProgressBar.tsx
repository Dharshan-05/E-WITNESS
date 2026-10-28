import React from 'react';

interface UploadProgressBarProps {
  /** Progress value 0-100 */
  progress: number;
  /** File name for ARIA labeling */
  filename: string;
  /** Optional status text displayed alongside progress */
  statusText?: string;
  /** Visual variant */
  variant?: 'default' | 'success' | 'error';
}

/**
 * Accessible evidence upload progress bar with ARIA live announcements.
 */
export const UploadProgressBar: React.FC<UploadProgressBarProps> = ({
  progress,
  filename,
  statusText,
  variant = 'default',
}) => {
  const clampedProgress = Math.min(100, Math.max(0, Math.round(progress)));

  const barColor =
    variant === 'success'
      ? 'bg-emerald-500'
      : variant === 'error'
        ? 'bg-red-500'
        : 'bg-indigo-600';

  return (
    <div className="w-full space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-600 truncate max-w-[70%]" title={filename}>
          {statusText || 'Uploading…'}
        </span>
        <span className="text-slate-500 font-mono tabular-nums shrink-0 ml-2">
          {clampedProgress}%
        </span>
      </div>
      <div
        className="h-2 w-full bg-slate-100 rounded-full overflow-hidden"
        role="progressbar"
        aria-valuenow={clampedProgress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Upload progress for ${filename}`}
      >
        <div
          className={`h-full rounded-full transition-all duration-300 ease-out ${barColor}`}
          style={{ width: `${clampedProgress}%` }}
        />
      </div>
      {/* Screen reader live announcement */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {clampedProgress === 100
          ? `Upload complete for ${filename}`
          : `${filename} upload: ${clampedProgress} percent`}
      </div>
    </div>
  );
};
