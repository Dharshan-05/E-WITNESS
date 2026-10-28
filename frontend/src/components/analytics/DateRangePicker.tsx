import React, { useState } from 'react';
import { Calendar, RefreshCw, AlertCircle } from 'lucide-react';
import { clsx } from 'clsx';
import type { TimeBucket } from '../../types/analytics';

export interface DateRangeOption {
  label: string;
  days: number;
}

export interface DateRangePickerProps {
  startDate: string | null;
  endDate: string | null;
  bucket?: TimeBucket;
  onFilterChange: (params: { startDate: string | null; endDate: string | null; bucket?: TimeBucket }) => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  className?: string;
}

export const DateRangePicker: React.FC<DateRangePickerProps> = ({
  startDate,
  endDate,
  bucket = 'day',
  onFilterChange,
  onRefresh,
  isRefreshing = false,
  className,
}) => {
  const [activePreset, setActivePreset] = useState<number | 'custom'>(30);
  const [customStart, setCustomStart] = useState<string>(
    startDate ? startDate.substring(0, 10) : ''
  );
  const [customEnd, setCustomEnd] = useState<string>(
    endDate ? endDate.substring(0, 10) : ''
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const presets: DateRangeOption[] = [
    { label: '7D', days: 7 },
    { label: '30D', days: 30 },
    { label: '90D', days: 90 },
    { label: '365D', days: 365 },
  ];

  const handlePresetSelect = (days: number) => {
    setActivePreset(days);
    setErrorMessage(null);

    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - days);

    onFilterChange({
      startDate: start.toISOString(),
      endDate: end.toISOString(),
      bucket,
    });
  };

  const handleCustomApply = () => {
    if (!customStart || !customEnd) {
      setErrorMessage('Please select both start and end dates.');
      return;
    }

    const start = new Date(customStart + 'T00:00:00Z');
    const end = new Date(customEnd + 'T23:59:59Z');

    if (start > end) {
      setErrorMessage('Start date cannot be after end date.');
      return;
    }

    const diffDays = (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24);
    if (diffDays > 366) {
      setErrorMessage('Observation window cannot exceed 366 days.');
      return;
    }

    setErrorMessage(null);
    setActivePreset('custom');
    onFilterChange({
      startDate: start.toISOString(),
      endDate: end.toISOString(),
      bucket,
    });
  };

  const handleBucketChange = (newBucket: TimeBucket) => {
    onFilterChange({
      startDate,
      endDate,
      bucket: newBucket,
    });
  };

  return (
    <div
      className={clsx(
        'flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-xs',
        className
      )}
      role="search"
      aria-label="Analytics date range and interval filters"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider pl-1">
          <Calendar className="h-4 w-4 text-slate-400" aria-hidden="true" />
          <span>Window:</span>
        </span>

        {/* Preset Buttons */}
        <div className="inline-flex rounded-lg border border-slate-200 p-0.5 bg-slate-50">
          {presets.map((p) => (
            <button
              key={p.days}
              type="button"
              onClick={() => handlePresetSelect(p.days)}
              className={clsx(
                'rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500',
                activePreset === p.days
                  ? 'bg-slate-900 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900'
              )}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Custom Date Inputs */}
        <div className="flex items-center gap-1.5 text-xs">
          <input
            type="date"
            value={customStart}
            onChange={(e) => setCustomStart(e.target.value)}
            className="rounded-md border border-slate-200 px-2 py-1 text-slate-700 font-mono text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            aria-label="Filter start date"
          />
          <span className="text-slate-400">to</span>
          <input
            type="date"
            value={customEnd}
            onChange={(e) => setCustomEnd(e.target.value)}
            className="rounded-md border border-slate-200 px-2 py-1 text-slate-700 font-mono text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            aria-label="Filter end date"
          />
          <button
            type="button"
            onClick={handleCustomApply}
            className="rounded-md border border-slate-300 bg-white px-2.5 py-1 font-semibold text-xs text-slate-700 hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            Apply
          </button>
        </div>

        {/* Bucket Interval selector */}
        <div className="flex items-center gap-1.5 pl-2 border-l border-slate-200 text-xs">
          <span className="text-slate-500 font-medium">Bucket:</span>
          <select
            value={bucket}
            onChange={(e) => handleBucketChange(e.target.value as TimeBucket)}
            className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 font-medium focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            aria-label="Time-series aggregation bucket"
          >
            <option value="hour">Hourly</option>
            <option value="day">Daily</option>
            <option value="week">Weekly</option>
            <option value="month">Monthly</option>
          </select>
        </div>
      </div>

      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-xs hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
          aria-label="Refresh dashboard data"
        >
          <RefreshCw className={clsx('h-3.5 w-3.5', isRefreshing && 'animate-spin text-indigo-600')} />
          <span>Refresh</span>
        </button>
      )}

      {errorMessage && (
        <div className="w-full flex items-center gap-1.5 text-xs text-rose-600 bg-rose-50 px-3 py-1.5 rounded-lg border border-rose-200 mt-1">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{errorMessage}</span>
        </div>
      )}
    </div>
  );
};
