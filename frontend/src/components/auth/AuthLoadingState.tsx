import React from 'react';
import { Shield } from 'lucide-react';

interface AuthLoadingStateProps {
  message?: string;
}

export const AuthLoadingState: React.FC<AuthLoadingStateProps> = ({
  message = 'Verifying institutional session credentials...',
}) => {
  return (
    <div
      className="flex min-h-[50vh] flex-col items-center justify-center p-6 text-center"
      role="status"
      aria-live="polite"
    >
      <div className="relative mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-700 shadow-sm border border-indigo-100 animate-pulse">
        <Shield className="h-8 w-8 text-indigo-700" />
      </div>
      <h3 className="text-base font-semibold text-slate-800 tracking-tight mb-1">
        E-WITNESS Authentication
      </h3>
      <p className="text-sm text-slate-500 max-w-sm">{message}</p>
      <span className="sr-only">Loading session...</span>
    </div>
  );
};
