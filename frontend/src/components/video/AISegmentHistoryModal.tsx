import React, { useEffect, useState } from 'react';
import {
  History,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  Loader2,
  Clock,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import type { CaseAISegmentRead, CaseAISegmentHistoryItemRead } from '../../types/case';
import { getCaseAISegmentReviewHistory } from '../../api/case';

interface AISegmentHistoryModalProps {
  caseId: string;
  segment: CaseAISegmentRead;
  isOpen: boolean;
  onClose: () => void;
}

export const AISegmentHistoryModal: React.FC<AISegmentHistoryModalProps> = ({
  caseId,
  segment,
  isOpen,
  onClose,
}) => {
  const [history, setHistory] = useState<CaseAISegmentHistoryItemRead[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    let isMounted = true;
    setIsLoading(true);
    setError(null);

    getCaseAISegmentReviewHistory(caseId, segment.segment_id || segment.id)
      .then((items) => {
        if (isMounted) {
          setHistory(items);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setError(
            err instanceof Error ? err.message : 'Failed to retrieve segment review history.'
          );
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [caseId, segment, isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="history-modal-title"
    >
      <div className="w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden my-8">
        {/* Header */}
        <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="space-y-0.5">
            <h3 id="history-modal-title" className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <History className="h-4 w-4 text-indigo-600" />
              Segment Review Decision Audit Log
            </h3>
            <p className="text-xs text-slate-500">
              Immutable chain-of-custody audit trail of human review determinations.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-lg leading-none p-1"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="p-5 max-h-[60vh] overflow-y-auto space-y-3">
          {isLoading && (
            <div className="p-8 text-center text-slate-400 space-y-2">
              <Loader2 className="h-6 w-6 animate-spin mx-auto text-indigo-500" />
              <p className="text-xs">Loading decision audit log…</p>
            </div>
          )}

          {error && (
            <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-800 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {!isLoading && !error && history.length === 0 && (
            <div className="p-8 text-center text-slate-400 space-y-2">
              <Clock className="h-8 w-8 mx-auto text-slate-300" />
              <p className="text-sm font-medium text-slate-600">No Review History</p>
              <p className="text-xs max-w-xs mx-auto">
                No authorized human review determinations have been recorded for this AI candidate segment yet.
              </p>
            </div>
          )}

          {!isLoading &&
            !error &&
            history.length > 0 &&
            history.map((item, idx) => (
              <div
                key={item.event_id || idx}
                className="p-3.5 bg-slate-50 rounded-lg border border-slate-200 space-y-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono font-bold text-slate-700 bg-slate-200 px-1.5 py-0.5 rounded text-[10px]">
                      REV {item.decision_revision}
                    </span>
                    {item.is_override && (
                      <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-800 border border-purple-200">
                        SUPERVISOR OVERRIDE
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] text-slate-400">
                    {new Date(item.timestamp).toLocaleString()}
                  </span>
                </div>

                {/* Transition */}
                <div className="flex items-center gap-2 text-xs font-semibold">
                  <Badge variant="default" size="sm">
                    {item.previous_review_status || 'PENDING'}
                  </Badge>
                  <ArrowRight className="h-3 w-3 text-slate-400" />
                  <Badge
                    variant={
                      item.new_review_status === 'confirmed'
                        ? 'success'
                        : item.new_review_status === 'rejected'
                        ? 'danger'
                        : 'purple'
                    }
                    size="sm"
                  >
                    {item.new_review_status.toUpperCase()}
                  </Badge>
                </div>

                {/* Actor */}
                <div className="text-[11px] text-slate-500 flex items-center gap-2">
                  <ShieldCheck className="h-3 w-3 text-slate-400" />
                  <span>
                    Reviewer: <code className="text-slate-700">{item.actor_id?.slice(0, 8)}…</code> (
                    {item.actor_role || 'investigator'})
                  </span>
                </div>

                {/* Corrected label */}
                {item.corrected_label && (
                  <div className="text-[11px] text-slate-600">
                    <strong>Corrected Label:</strong> {item.corrected_label}
                  </div>
                )}

                {/* Rationale */}
                {item.review_rationale && (
                  <div className="p-2 bg-white rounded border border-slate-200 text-slate-700 text-[11px] leading-relaxed">
                    <strong>Rationale:</strong> {item.review_rationale}
                  </div>
                )}
              </div>
            ))}
        </div>

        {/* Footer */}
        <div className="p-3 bg-slate-50 border-t border-slate-200 flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>
            Close Audit Log
          </Button>
        </div>
      </div>
    </div>
  );
};
