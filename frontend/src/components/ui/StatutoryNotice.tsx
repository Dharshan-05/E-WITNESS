import React from 'react';
import { ShieldCheck, Info } from 'lucide-react';
import { AI_ADVISORY_DISCLAIMER } from '../../types/ai';

export const StatutoryNotice: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  if (compact) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500 py-1.5 px-3 bg-slate-100 rounded-md border border-slate-200">
        <ShieldCheck className="h-4 w-4 text-slate-500 shrink-0" aria-hidden="true" />
        <span className="truncate">
          <strong>Advisory Notice:</strong> AI predictions are probabilistic investigative leads requiring human review.
        </span>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-4 text-xs text-slate-600">
      <div className="flex items-start gap-3">
        <Info className="h-5 w-5 text-indigo-600 shrink-0 mt-0.5" aria-hidden="true" />
        <div>
          <h6 className="font-semibold text-slate-900 text-xs tracking-wide uppercase">
            Mandatory Statutory & Evidence Custody Governance
          </h6>
          <p className="mt-1 leading-relaxed text-slate-600">
            {AI_ADVISORY_DISCLAIMER}
          </p>
          <p className="mt-1.5 text-slate-500">
            All evidence files maintain cryptographic SHA-256 integrity in isolated object storage. Biometric facial matching and mass surveillance are permanently disabled fail-closed.
          </p>
        </div>
      </div>
    </div>
  );
};
