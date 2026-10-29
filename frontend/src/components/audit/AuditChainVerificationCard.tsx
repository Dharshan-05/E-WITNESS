import React from 'react';
import { ShieldCheck, AlertTriangle, RefreshCw, Info, CheckCircle2 } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import type { AuditVerificationReport } from '../../types/audit';

export interface AuditChainVerificationCardProps {
  report: AuditVerificationReport | null;
  isVerifying: boolean;
  onVerify: () => void;
  onClose?: () => void;
}

export const AuditChainVerificationCard: React.FC<AuditChainVerificationCardProps> = ({
  report,
  isVerifying,
  onVerify,
  onClose,
}) => {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-700">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              Cryptographic Hash Chain Integrity Verification
            </h3>
            <p className="text-xs text-slate-500">
              Evaluates consecutive SHA-256 Merkle links and monotonic sequence continuity across the ledger.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={onVerify}
            isLoading={isVerifying}
            className="flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Verify Ledger</span>
          </Button>
          {onClose && (
            <Button type="button" variant="ghost" size="sm" onClick={onClose} className="text-xs">
              Dismiss
            </Button>
          )}
        </div>
      </div>

      {report && (
        <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-3 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-2">
            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-700">Verification Status:</span>
              {report.chain_valid ? (
                <Badge variant="success" className="flex items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Chain Verified (Valid)</span>
                </Badge>
              ) : (
                <Badge variant="danger" className="flex items-center gap-1">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  <span>Integrity Compromised</span>
                </Badge>
              )}
            </div>
            <div className="text-slate-500 font-mono text-[11px]">
              Evaluated at: {new Date(report.verified_at).toISOString()}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <span className="text-slate-500 block">Total Evaluated Records</span>
              <span className="font-bold text-slate-900 text-sm">{report.total_events_verified}</span>
            </div>
            <div>
              <span className="text-slate-500 block">Sequence Bounds</span>
              <span className="font-mono text-slate-800">
                {report.first_sequence_number != null ? `#${report.first_sequence_number}` : 'None'} →{' '}
                {report.last_sequence_number != null ? `#${report.last_sequence_number}` : 'None'}
              </span>
            </div>
            <div>
              <span className="text-slate-500 block">Tampered Records</span>
              <span
                className={`font-bold ${
                  report.tampered_event_ids.length > 0 ? 'text-rose-600' : 'text-emerald-600'
                }`}
              >
                {report.tampered_event_ids.length} detected
              </span>
            </div>
          </div>

          {report.errors.length > 0 && (
            <div className="p-3 rounded bg-rose-50 border border-rose-200 text-rose-800 space-y-1">
              <div className="font-semibold flex items-center gap-1">
                <AlertTriangle className="h-4 w-4" />
                <span>Verification Anomalies Detected:</span>
              </div>
              <ul className="list-disc list-inside text-[11px] space-y-0.5">
                {report.errors.map((err, idx) => (
                  <li key={idx}>{err}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-start gap-2 pt-2 border-t border-slate-200 text-[11px] text-slate-500">
            <Info className="h-3.5 w-3.5 text-slate-400 shrink-0 mt-0.5" />
            <p className="leading-relaxed">{report.disclaimer}</p>
          </div>
        </div>
      )}
    </div>
  );
};
