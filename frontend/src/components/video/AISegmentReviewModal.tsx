import React, { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  ArrowUpRight,
  ShieldAlert,
  Loader2,
  FileCheck,
} from 'lucide-react';
import { Button } from '../ui/Button';
import type { CaseAISegmentRead, CaseAISegmentReviewRequest } from '../../types/case';
import { formatTime } from './video.utils';

interface AISegmentReviewModalProps {
  segment: CaseAISegmentRead;
  isOpen: boolean;
  onClose: () => void;
  onSubmitReview: (
    payload: CaseAISegmentReviewRequest,
    createFinding?: {
      findingType: string;
      title: string;
      description: string;
    }
  ) => Promise<void>;
  isSupervisor?: boolean;
}

export const AISegmentReviewModal: React.FC<AISegmentReviewModalProps> = ({
  segment,
  isOpen,
  onClose,
  onSubmitReview,
  isSupervisor = false,
}) => {
  const [decision, setDecision] = useState<
    'confirmed' | 'rejected' | 'inconclusive' | 'escalated'
  >('confirmed');
  const [rationale, setRationale] = useState<string>('');
  const [correctedLabel, setCorrectedLabel] = useState<string>('');
  const [isOverride, setIsOverride] = useState<boolean>(false);
  const [createFinding, setCreateFinding] = useState<boolean>(false);
  const [findingType, setFindingType] = useState<string>('preliminary');
  const [findingTitle, setFindingTitle] = useState<string>('');

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const cleanRationale = rationale.trim();
    if (cleanRationale.length < 10) {
      setError('Review rationale must be at least 10 characters detailing your factual findings.');
      return;
    }
    if (cleanRationale.length > 1000) {
      setError('Review rationale cannot exceed 1000 characters.');
      return;
    }

    if (decision === 'rejected' && !cleanRationale) {
      setError('Mandatory documented reason required when rejecting an AI candidate segment.');
      return;
    }

    if (createFinding && !findingTitle.trim()) {
      setError('Finding title is required when recording as a formal case finding.');
      return;
    }

    const payload: CaseAISegmentReviewRequest = {
      review_status: decision,
      review_rationale: cleanRationale,
      corrected_label: correctedLabel.trim() || undefined,
      expected_review_status: segment.review_status,
      expected_revision: segment.decision_revision,
      is_override: isSupervisor && isOverride,
    };

    setIsSubmitting(true);
    try {
      await onSubmitReview(
        payload,
        createFinding
          ? {
              findingType,
              title: findingTitle.trim(),
              description: cleanRationale,
            }
          : undefined
      );
      onClose();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to record human review determination.';
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-modal-title"
    >
      <div className="w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden my-8">
        {/* Modal Header */}
        <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="space-y-0.5">
            <h3 id="review-modal-title" className="text-sm font-semibold text-slate-800">
              Human Review Determination
            </h3>
            <p className="text-xs text-slate-500">
              Authorized evaluation of AI candidate segment [{formatTime(segment.start_seconds)} –{' '}
              {formatTime(segment.end_seconds)}]
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="text-slate-400 hover:text-slate-600 text-lg leading-none p-1"
          >
            ×
          </button>
        </div>

        {/* Advisory Legal Disclaimer */}
        <div className="p-3 bg-amber-50 border-b border-amber-200 flex items-start gap-2 text-xs text-amber-900">
          <ShieldAlert className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-[11px] leading-tight">
            <strong>Institutional AI Governance Notice:</strong> AI detections are probabilistic
            candidate observations. Human reviewer determination is authoritative and entered into
            the immutable chain-of-custody audit log.
          </div>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* Segment Summary Card */}
          <div className="p-3 bg-slate-50 rounded-lg border border-slate-200 text-xs text-slate-700 grid grid-cols-2 gap-2">
            <div>
              <span className="text-slate-400 text-[11px]">Time Range:</span>
              <p className="font-mono font-semibold text-slate-800">
                {formatTime(segment.start_seconds)} – {formatTime(segment.end_seconds)} (
                {segment.duration_seconds.toFixed(1)}s)
              </p>
            </div>
            <div>
              <span className="text-slate-400 text-[11px]">Model Score:</span>
              <p className="font-semibold text-slate-800">
                {((segment.raw_score ?? segment.score) * 100).toFixed(1)}% (
                {segment.model_name || 'classifier'})
              </p>
            </div>
            <div>
              <span className="text-slate-400 text-[11px]">Current Status:</span>
              <p className="font-semibold text-slate-800 uppercase">
                {segment.review_status} (Rev {segment.decision_revision})
              </p>
            </div>
            <div>
              <span className="text-slate-400 text-[11px]">Original Label:</span>
              <p className="font-semibold text-slate-800">{segment.label}</p>
            </div>
          </div>

          {/* Determination Selector */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-700">
              Review Determination <span className="text-rose-500">*</span>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setDecision('confirmed')}
                className={`p-2.5 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition-all ${
                  decision === 'confirmed'
                    ? 'border-emerald-600 bg-emerald-50 text-emerald-800 ring-2 ring-emerald-200'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700'
                }`}
              >
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                Confirm
              </button>

              <button
                type="button"
                onClick={() => setDecision('rejected')}
                className={`p-2.5 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition-all ${
                  decision === 'rejected'
                    ? 'border-rose-600 bg-rose-50 text-rose-800 ring-2 ring-rose-200'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700'
                }`}
              >
                <XCircle className="h-4 w-4 text-rose-600" />
                Reject
              </button>

              <button
                type="button"
                onClick={() => setDecision('inconclusive')}
                className={`p-2.5 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition-all ${
                  decision === 'inconclusive'
                    ? 'border-slate-600 bg-slate-100 text-slate-800 ring-2 ring-slate-200'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700'
                }`}
              >
                <HelpCircle className="h-4 w-4 text-slate-600" />
                Inconclusive
              </button>

              <button
                type="button"
                onClick={() => setDecision('escalated')}
                className={`p-2.5 rounded-lg border text-xs font-semibold flex items-center justify-center gap-2 transition-all ${
                  decision === 'escalated'
                    ? 'border-purple-600 bg-purple-50 text-purple-800 ring-2 ring-purple-200'
                    : 'border-slate-200 hover:border-slate-300 text-slate-700'
                }`}
              >
                <ArrowUpRight className="h-4 w-4 text-purple-600" />
                Escalate
              </button>
            </div>
          </div>

          {/* Corrected Label (Optional) */}
          <div className="space-y-1">
            <label className="block text-xs font-semibold text-slate-700">
              Human-Corrected Label (Optional)
            </label>
            <input
              type="text"
              value={correctedLabel}
              onChange={(e) => setCorrectedLabel(e.target.value)}
              placeholder="e.g. physical_altercation, sporting_contact, fall..."
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
            />
          </div>

          {/* Review Rationale */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-slate-700">
                Review Rationale & Observations <span className="text-rose-500">*</span>
              </label>
              <span className="text-[11px] text-slate-400 font-mono">
                {rationale.length}/1000 (min 10)
              </span>
            </div>
            <textarea
              rows={3}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="Provide detailed factual justification for your determination..."
              className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
            />
          </div>

          {/* Supervisor Override Toggle (Only if user has supervisor role) */}
          {isSupervisor && segment.review_status !== 'pending_review' && (
            <div className="p-3 bg-purple-50 rounded-lg border border-purple-200 space-y-1.5">
              <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-purple-900">
                <input
                  type="checkbox"
                  checked={isOverride}
                  onChange={(e) => setIsOverride(e.target.checked)}
                  className="rounded text-purple-600 focus:ring-purple-500"
                />
                Apply as Authorized Supervisor Override
              </label>
              <p className="text-[11px] text-purple-700">
                Overriding will advance the decision revision count to Rev{' '}
                {segment.decision_revision + 1} and record an authoritative supervisor event.
              </p>
            </div>
          )}

          {/* Record as Formal Case Finding (Optional when confirmed) */}
          {decision === 'confirmed' && (
            <div className="p-3 bg-indigo-50/80 rounded-lg border border-indigo-200 space-y-2">
              <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-indigo-900">
                <input
                  type="checkbox"
                  checked={createFinding}
                  onChange={(e) => setCreateFinding(e.target.checked)}
                  className="rounded text-indigo-600 focus:ring-indigo-500"
                />
                <FileCheck className="h-3.5 w-3.5 text-indigo-600" />
                Record Formal Case Finding for this Segment
              </label>

              {createFinding && (
                <div className="space-y-2 pt-1 border-t border-indigo-100">
                  <div>
                    <label className="block text-[11px] font-semibold text-indigo-950 mb-0.5">
                      Finding Title:
                    </label>
                    <input
                      type="text"
                      value={findingTitle}
                      onChange={(e) => setFindingTitle(e.target.value)}
                      placeholder="e.g. Corroborated altercations at entrance"
                      className="w-full px-2.5 py-1.5 text-xs rounded border border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-semibold text-indigo-950 mb-0.5">
                      Finding Type:
                    </label>
                    <select
                      value={findingType}
                      onChange={(e) => setFindingType(e.target.value)}
                      className="w-full px-2.5 py-1.5 text-xs rounded border border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
                    >
                      <option value="inculpatory">Inculpatory</option>
                      <option value="exculpatory">Exculpatory</option>
                      <option value="procedural">Procedural</option>
                      <option value="inconclusive">Inconclusive</option>
                      <option value="preliminary">Preliminary</option>
                    </select>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Modal Footer Actions */}
          <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
            <Button
              variant="outline"
              size="sm"
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              type="submit"
              disabled={isSubmitting || rationale.trim().length < 10}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                  Recording Determination…
                </>
              ) : (
                'Submit Determination'
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
