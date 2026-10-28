import React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  ArrowUpRight,
  Clock,
  History,
  ShieldAlert,
  Play,
  FileEdit,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import type { CaseAISegmentRead } from '../../types/case';
import { formatTime } from './video.utils';

interface AISegmentsListProps {
  segments: CaseAISegmentRead[];
  currentTime: number;
  selectedSegmentId?: string | null;
  onSeekTo: (seconds: number) => void;
  onReviewSegment: (segment: CaseAISegmentRead) => void;
  onViewHistory: (segment: CaseAISegmentRead) => void;
  canReview?: boolean;
}

export const AISegmentsList: React.FC<AISegmentsListProps> = ({
  segments,
  currentTime,
  selectedSegmentId,
  onSeekTo,
  onReviewSegment,
  onViewHistory,
  canReview = true,
}) => {
  return (
    <div className="flex flex-col h-full bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
        <div>
          <h4 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            AI Candidate Annotations
            <Badge variant="primary" size="sm">
              {segments.length}
            </Badge>
          </h4>
          <p className="text-xs text-slate-500">
            Automated candidate detections requiring human investigator review.
          </p>
        </div>
      </div>

      {/* Mandatory Statutory Advisory Banner */}
      <div className="p-3 bg-amber-50/80 border-b border-amber-200/80 text-amber-900 flex items-start gap-2 text-xs">
        <ShieldAlert className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
        <div className="space-y-0.5 leading-tight">
          <p className="font-semibold text-amber-800">Non-Authoritative Advisory Leads</p>
          <p className="text-[11px] text-amber-700">
            AI candidate outputs are strictly advisory. They must never independently determine
            guilt, identify a suspect, or substitute for formal case adjudication.
          </p>
        </div>
      </div>

      {/* Segments List or Empty State */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {segments.length === 0 ? (
          <div className="p-8 text-center text-slate-400 space-y-2">
            <Clock className="h-8 w-8 mx-auto text-slate-300" />
            <p className="text-sm font-medium text-slate-600">No Candidate Segments</p>
            <p className="text-xs max-w-xs mx-auto">
              No AI violence or action candidate segments have been linked to this video evidence
              item.
            </p>
          </div>
        ) : (
          segments.map((seg) => {
            const isActive =
              currentTime >= seg.start_seconds && currentTime <= seg.end_seconds;
            const isSelected = selectedSegmentId === seg.id;

            const rawScorePct = ((seg.raw_score ?? seg.score) * 100).toFixed(1);
            const calibratedScorePct =
              seg.calibrated_score !== null && seg.calibrated_score !== undefined
                ? (seg.calibrated_score * 100).toFixed(1)
                : null;

            // Status Badge Variant
            let statusBadge = (
              <Badge variant="warning" size="sm" className="flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" />
                PENDING REVIEW
              </Badge>
            );

            if (seg.review_status === 'confirmed') {
              statusBadge = (
                <Badge variant="success" size="sm" className="flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  CONFIRMED
                </Badge>
              );
            } else if (seg.review_status === 'rejected') {
              statusBadge = (
                <Badge variant="danger" size="sm" className="flex items-center gap-1">
                  <XCircle className="h-3 w-3" />
                  REJECTED
                </Badge>
              );
            } else if (seg.review_status === 'inconclusive') {
              statusBadge = (
                <Badge variant="default" size="sm" className="flex items-center gap-1">
                  <HelpCircle className="h-3 w-3" />
                  INCONCLUSIVE
                </Badge>
              );
            } else if (seg.review_status === 'escalated') {
              statusBadge = (
                <Badge variant="purple" size="sm" className="flex items-center gap-1">
                  <ArrowUpRight className="h-3 w-3" />
                  ESCALATED
                </Badge>
              );
            }

            return (
              <div
                key={seg.id}
                className={`p-3.5 rounded-lg border transition-all ${
                  isActive
                    ? 'border-indigo-500 bg-indigo-50/60 ring-2 ring-indigo-200'
                    : isSelected
                    ? 'border-slate-400 bg-slate-50'
                    : 'border-slate-200 bg-white hover:border-slate-300'
                }`}
              >
                {/* Top Row: Timestamps and Status */}
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onSeekTo(seg.start_seconds)}
                    title="Seek video to segment start timestamp"
                    className="flex items-center gap-1.5 font-mono text-xs font-bold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 px-2 py-0.5 rounded border border-indigo-200 transition-colors"
                  >
                    <Play className="h-3 w-3 fill-current" />
                    {formatTime(seg.start_seconds)} – {formatTime(seg.end_seconds)}
                    <span className="text-[10px] text-indigo-500 font-normal">
                      ({seg.duration_seconds.toFixed(1)}s)
                    </span>
                  </button>

                  <div className="flex items-center gap-1.5 flex-wrap">
                    {statusBadge}
                    {seg.is_override && (
                      <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-800 border border-purple-200">
                        OVERRIDE
                      </span>
                    )}
                  </div>
                </div>

                {/* Candidate Prediction Details */}
                <div className="mt-2 text-xs text-slate-700 space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-900">
                      Label: {seg.human_corrected_label || seg.label}
                    </span>
                    <span className="text-[11px] text-slate-500">
                      Score: <strong>{rawScorePct}%</strong>
                      {calibratedScorePct && ` (Calibrated: ${calibratedScorePct}%)`}
                    </span>
                  </div>

                  {seg.model_name && (
                    <p className="text-[11px] text-slate-400 font-mono">
                      Model: {seg.model_name} {seg.model_version ? `v${seg.model_version}` : ''}
                    </p>
                  )}

                  {seg.review_notes && (
                    <div className="mt-1.5 p-2 bg-slate-50 rounded border border-slate-200 text-[11px] text-slate-600">
                      <strong className="text-slate-700">Reviewer Note:</strong> {seg.review_notes}
                    </div>
                  )}
                </div>

                {/* Bottom Actions */}
                <div className="mt-3 pt-2.5 border-t border-slate-100 flex items-center justify-between gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onViewHistory(seg)}
                    title="View decision revision audit log"
                    className="text-xs text-slate-600 hover:text-slate-800 p-1"
                  >
                    <History className="h-3.5 w-3.5 mr-1" />
                    History (Rev {seg.decision_revision})
                  </Button>

                  {canReview && (
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => onReviewSegment(seg)}
                      className="text-xs"
                    >
                      <FileEdit className="h-3.5 w-3.5 mr-1" />
                      Review Decision
                    </Button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
