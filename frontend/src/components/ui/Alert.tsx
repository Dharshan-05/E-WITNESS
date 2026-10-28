import React from 'react';
import { AlertCircle, CheckCircle2, AlertTriangle, Info } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'info' | 'success' | 'warning' | 'error';
  title?: string;
  icon?: boolean;
}

export const Alert: React.FC<AlertProps> = ({
  className,
  variant = 'info',
  title,
  icon = true,
  children,
  ...props
}) => {
  const styles = {
    info: {
      container: 'bg-sky-50 border-sky-200 text-sky-900',
      icon: <Info className="h-5 w-5 text-sky-600 shrink-0" aria-hidden="true" />,
      titleColor: 'text-sky-950 font-semibold',
    },
    success: {
      container: 'bg-emerald-50 border-emerald-200 text-emerald-900',
      icon: <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" aria-hidden="true" />,
      titleColor: 'text-emerald-950 font-semibold',
    },
    warning: {
      container: 'bg-amber-50 border-amber-200 text-amber-900',
      icon: <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0" aria-hidden="true" />,
      titleColor: 'text-amber-950 font-semibold',
    },
    error: {
      container: 'bg-rose-50 border-rose-200 text-rose-900',
      icon: <AlertCircle className="h-5 w-5 text-rose-600 shrink-0" aria-hidden="true" />,
      titleColor: 'text-rose-950 font-semibold',
    },
  };

  const selected = styles[variant];

  return (
    <div
      role="alert"
      className={twMerge(
        clsx(
          'flex gap-3 rounded-lg border p-4 text-sm leading-relaxed transition-all',
          selected.container,
          className
        )
      )}
      {...props}
    >
      {icon && selected.icon}
      <div className="flex-1">
        {title && <h5 className={clsx('mb-1 text-sm leading-none tracking-tight', selected.titleColor)}>{title}</h5>}
        <div className="text-sm opacity-95">{children}</div>
      </div>
    </div>
  );
};
