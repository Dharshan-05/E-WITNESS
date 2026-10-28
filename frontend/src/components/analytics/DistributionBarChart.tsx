import React from 'react';
import { clsx } from 'clsx';
import { BarChart3 } from 'lucide-react';

export interface DistributionBarChartProps {
  title: string;
  subtitle?: string;
  data: Record<string, number>;
  totalCount?: number;
  colorMap?: Record<string, string>;
  defaultColor?: string;
  valueFormatter?: (val: number) => string;
  emptyMessage?: string;
  className?: string;
}

export const DistributionBarChart: React.FC<DistributionBarChartProps> = ({
  title,
  subtitle,
  data,
  totalCount,
  colorMap = {},
  defaultColor = 'bg-indigo-600',
  valueFormatter = (val) => val.toLocaleString(),
  emptyMessage = 'No distribution data available.',
  className,
}) => {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = totalCount ?? entries.reduce((acc, [, val]) => acc + val, 0);

  if (entries.length === 0 || total === 0) {
    return (
      <div className={clsx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm', className)}>
        <h4 className="text-sm font-bold text-slate-900">{title}</h4>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
        <div className="flex h-36 flex-col items-center justify-center text-center text-slate-400">
          <BarChart3 className="h-7 w-7 mb-2 stroke-1" aria-hidden="true" />
          <p className="text-xs">{emptyMessage}</p>
        </div>
      </div>
    );
  }

  const formatKeyName = (key: string): string => {
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

  return (
    <div
      className={clsx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm flex flex-col', className)}
      role="region"
      aria-label={`${title} distribution chart`}
    >
      <div className="flex items-center justify-between mb-3">
        <div>
          <h4 className="text-sm font-bold text-slate-900">{title}</h4>
          {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
        </div>
        <span className="text-xs font-mono font-semibold text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
          Total: {total.toLocaleString()}
        </span>
      </div>

      <ul className="space-y-3 mt-1" role="list">
        {entries.map(([key, count]) => {
          const percentage = total > 0 ? (count / total) * 100 : 0;
          const barColor = colorMap[key] || defaultColor;

          return (
            <li key={key} className="space-y-1">
              <div className="flex items-center justify-between text-xs font-medium">
                <span className="text-slate-700 truncate mr-2" title={formatKeyName(key)}>
                  {formatKeyName(key)}
                </span>
                <span className="text-slate-500 font-mono shrink-0">
                  {valueFormatter(count)}{' '}
                  <span className="text-slate-400 text-[11px]">({percentage.toFixed(1)}%)</span>
                </span>
              </div>
              <div
                className="h-2 w-full overflow-hidden rounded-full bg-slate-100"
                role="progressbar"
                aria-valuenow={count}
                aria-valuemin={0}
                aria-valuemax={total}
                aria-label={`${formatKeyName(key)}: ${count} of ${total}`}
              >
                <div
                  className={clsx('h-full rounded-full transition-all duration-300', barColor)}
                  style={{ width: `${Math.min(100, Math.max(1, percentage))}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
};
