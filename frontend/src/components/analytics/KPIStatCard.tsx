import React from 'react';
import { clsx } from 'clsx';
import { HelpCircle } from 'lucide-react';

export interface KPIStatCardProps {
  title: string;
  value: number | string;
  sublabel?: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  variant?: 'default' | 'primary' | 'warning' | 'danger' | 'success';
  tooltip?: string;
  loading?: boolean;
  className?: string;
}

export const KPIStatCard: React.FC<KPIStatCardProps> = ({
  title,
  value,
  sublabel,
  icon,
  badge,
  variant = 'default',
  tooltip,
  loading = false,
  className,
}) => {
  const variantStyles = {
    default: 'border-slate-200 bg-white text-slate-900',
    primary: 'border-indigo-100 bg-indigo-50/50 text-indigo-950',
    warning: 'border-amber-200 bg-amber-50/50 text-amber-950',
    danger: 'border-rose-200 bg-rose-50/50 text-rose-950',
    success: 'border-emerald-200 bg-emerald-50/50 text-emerald-950',
  };

  const iconStyles = {
    default: 'bg-slate-100 text-slate-700',
    primary: 'bg-indigo-100 text-indigo-700',
    warning: 'bg-amber-100 text-amber-700',
    danger: 'bg-rose-100 text-rose-700',
    success: 'bg-emerald-100 text-emerald-700',
  };

  if (loading) {
    return (
      <div
        className={clsx(
          'rounded-xl border p-5 shadow-sm animate-pulse',
          variantStyles[variant],
          className
        )}
        aria-busy="true"
        aria-label={`Loading ${title}`}
      >
        <div className="flex items-center justify-between mb-3">
          <div className="h-4 w-28 bg-slate-200 rounded" />
          <div className="h-9 w-9 bg-slate-200 rounded-lg" />
        </div>
        <div className="h-8 w-20 bg-slate-200 rounded mb-2" />
        <div className="h-3 w-36 bg-slate-200 rounded" />
      </div>
    );
  }

  return (
    <div
      className={clsx(
        'rounded-xl border p-5 shadow-sm transition-all hover:shadow-md flex flex-col justify-between',
        variantStyles[variant],
        className
      )}
      role="region"
      aria-label={`${title}: ${value}`}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            {title}
          </span>
          {tooltip && (
            <span title={tooltip} className="cursor-help text-slate-400 hover:text-slate-600">
              <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
          )}
        </div>
        {icon && (
          <div
            className={clsx(
              'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg shadow-xs',
              iconStyles[variant]
            )}
            aria-hidden="true"
          >
            {icon}
          </div>
        )}
      </div>

      <div className="flex items-baseline gap-2">
        <div className="text-2xl sm:text-3xl font-extrabold tracking-tight font-mono text-slate-900">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </div>
        {badge && <div className="ml-auto">{badge}</div>}
      </div>

      {sublabel && (
        <div className="mt-2 text-xs text-slate-500 font-medium">
          {sublabel}
        </div>
      )}
    </div>
  );
};
