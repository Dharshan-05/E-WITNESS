import React from 'react';
import { X, ShieldCheck, Copy, Check, Clock, Server, User, FileText, KeyRound } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import type { SecurityAuditEvent } from '../../types/audit';

export interface AuditEventDetailModalProps {
  event: SecurityAuditEvent | null;
  isOpen: boolean;
  onClose: () => void;
}

export const AuditEventDetailModal: React.FC<AuditEventDetailModalProps> = ({
  event,
  isOpen,
  onClose,
}) => {
  const [copiedHash, setCopiedHash] = React.useState<string | null>(null);

  if (!isOpen || !event) return null;

  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedHash(label);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  const getOutcomeBadge = (outcome: string) => {
    switch (outcome?.toLowerCase()) {
      case 'success':
        return <Badge variant="success">Success</Badge>;
      case 'failure':
        return <Badge variant="danger">Failure</Badge>;
      case 'denied':
        return <Badge variant="warning">Access Denied</Badge>;
      default:
        return <Badge variant="default">{outcome}</Badge>;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm animate-in fade-in duration-150">
      <div
        className="w-full max-w-3xl rounded-xl bg-white shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[90vh]"
        role="dialog"
        aria-modal="true"
        aria-labelledby="audit-detail-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50/80">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-100">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <h2 id="audit-detail-title" className="text-base font-bold text-slate-900">
                Audit Record #{event.sequence_number}
              </h2>
              <p className="text-xs text-slate-500 font-mono">ID: {event.id}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
            aria-label="Close dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6 text-xs">
          {/* Top metadata grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 rounded-lg bg-slate-50 border border-slate-200">
            <div>
              <span className="text-slate-500 block mb-0.5">Classification Action</span>
              <span className="font-semibold text-slate-900 text-sm">{event.action}</span>
            </div>
            <div>
              <span className="text-slate-500 block mb-0.5">Execution Verdict</span>
              <div>{getOutcomeBadge(event.outcome)}</div>
            </div>
            <div>
              <span className="text-slate-500 block mb-0.5 flex items-center gap-1">
                <Clock className="h-3 w-3" /> Timestamp (UTC)
              </span>
              <span className="font-mono text-slate-800">{new Date(event.created_at).toISOString()}</span>
            </div>
            <div>
              <span className="text-slate-500 block mb-0.5 flex items-center gap-1">
                <Server className="h-3 w-3" /> Department Scope
              </span>
              <span className="font-mono text-slate-800">{event.department_id || 'System / Global'}</span>
            </div>
          </div>

          {/* Actor & Target Context */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 rounded-lg border border-slate-200 space-y-2">
              <div className="flex items-center gap-2 font-semibold text-slate-800 border-b border-slate-100 pb-2">
                <User className="h-4 w-4 text-slate-500" />
                <span>Initiating Actor Context</span>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-slate-500">Actor ID:</span>
                  <span className="font-mono font-medium text-slate-800">{event.actor_id || 'System Daemon'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Role:</span>
                  <span className="font-medium text-slate-800">{event.actor_role || 'N/A'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Source IP:</span>
                  <span className="font-mono text-slate-800">{event.actor_ip || 'N/A'}</span>
                </div>
                {event.actor_user_agent && (
                  <div>
                    <span className="text-slate-500 block">User Agent:</span>
                    <span className="text-[11px] text-slate-600 truncate block" title={event.actor_user_agent}>
                      {event.actor_user_agent}
                    </span>
                  </div>
                )}
              </div>
            </div>

            <div className="p-4 rounded-lg border border-slate-200 space-y-2">
              <div className="flex items-center gap-2 font-semibold text-slate-800 border-b border-slate-100 pb-2">
                <FileText className="h-4 w-4 text-slate-500" />
                <span>Target Entity Context</span>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between">
                  <span className="text-slate-500">Target Type:</span>
                  <span className="font-semibold text-slate-800 uppercase">{event.target_type}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Target ID:</span>
                  <span className="font-mono font-medium text-slate-800 truncate max-w-[200px]" title={event.target_id}>
                    {event.target_id}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Merkle Hash Chain Integrity */}
          <div className="p-4 rounded-lg border border-slate-200 bg-slate-50/50 space-y-2.5">
            <div className="flex items-center gap-2 font-semibold text-slate-800">
              <KeyRound className="h-4 w-4 text-indigo-600" />
              <span>Cryptographic Ledger Hash Chain</span>
            </div>

            <div className="space-y-2">
              <div>
                <div className="flex items-center justify-between text-[11px] text-slate-500 mb-0.5">
                  <span>SHA-256 Event Record Hash:</span>
                  <button
                    type="button"
                    onClick={() => handleCopy(event.event_hash, 'curr')}
                    className="flex items-center gap-1 text-indigo-600 hover:text-indigo-800"
                  >
                    {copiedHash === 'curr' ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                    <span>{copiedHash === 'curr' ? 'Copied' : 'Copy Hash'}</span>
                  </button>
                </div>
                <div className="p-2 rounded bg-white border border-slate-200 font-mono text-[11px] break-all text-slate-800">
                  {event.event_hash}
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between text-[11px] text-slate-500 mb-0.5">
                  <span>Previous Event Predecessor Digest:</span>
                  {event.previous_event_hash && (
                    <button
                      type="button"
                      onClick={() => handleCopy(event.previous_event_hash!, 'prev')}
                      className="flex items-center gap-1 text-indigo-600 hover:text-indigo-800"
                    >
                      {copiedHash === 'prev' ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                      <span>{copiedHash === 'prev' ? 'Copied' : 'Copy Hash'}</span>
                    </button>
                  )}
                </div>
                <div className="p-2 rounded bg-white border border-slate-200 font-mono text-[11px] break-all text-slate-600">
                  {event.previous_event_hash || 'None (Genesis Ledger Entry)'}
                </div>
              </div>
            </div>
          </div>

          {/* Structured Details JSON (Redacted) */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-800">Redacted Structured Action Details</span>
              <span className="text-[11px] text-slate-500">Sensitive credentials masked as ***REDACTED***</span>
            </div>
            <pre className="p-3.5 rounded-lg bg-slate-900 text-slate-100 font-mono text-[11px] overflow-x-auto max-h-48 border border-slate-800">
              {event.details ? JSON.stringify(event.details, null, 2) : '{\n  "message": "No extra payload recorded"\n}'}
            </pre>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end px-6 py-3 border-t border-slate-200 bg-slate-50">
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
};
