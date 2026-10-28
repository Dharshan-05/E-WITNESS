import React, { useState } from 'react';
import { X, ShieldAlert, UserCheck, ArrowRight, Lock } from 'lucide-react';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import type { CaseRead, CaseStatus } from '../../types/case';
import {
  transitionCaseStatus,
  submitCaseForReview,
  assignCase,
  placeLegalHold,
} from '../../api/case';

// ─── Status Transition Dialog ──────────────────────────────────────────────

interface TransitionModalProps {
  caseItem: CaseRead;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updated: CaseRead) => void;
}

const ALLOWED_TARGET_STATUSES: { value: CaseStatus; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'under_investigation', label: 'Under Investigation' },
  { value: 'pending_review', label: 'Pending Review' },
  { value: 'suspended', label: 'Suspended' },
  { value: 'resolved', label: 'Resolved' },
];

export const TransitionStatusModal: React.FC<TransitionModalProps> = ({
  caseItem,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [targetStatus, setTargetStatus] = useState<string>('under_investigation');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = reason.trim();
    if (trimmed.length < 10) {
      setError('A formal justification of at least 10 characters is required.');
      return;
    }

    setIsSubmitting(true);
    try {
      const updated = await transitionCaseStatus(caseItem.id, {
        target_status: targetStatus,
        reason: trimmed,
        expected_version_id: caseItem.version_id,
      });
      onSuccess(updated);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to transition case status.';
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="transition-title">
      <div className="w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden">
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <h2 id="transition-title" className="text-base font-bold text-slate-900 flex items-center gap-2">
            <ArrowRight className="h-4 w-4 text-indigo-600" />
            Transition Case Status
          </h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600 p-1 rounded" aria-label="Close dialog">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && <Alert variant="error">{error}</Alert>}

          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
              Current Status
            </label>
            <div className="font-mono text-sm font-bold text-slate-800 bg-slate-100 px-3 py-2 rounded">
              {caseItem.status.toUpperCase()} (v{caseItem.version_id})
            </div>
          </div>

          <div>
            <label htmlFor="target-status" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
              Target Lifecycle Status <span className="text-rose-500">*</span>
            </label>
            <select
              id="target-status"
              value={targetStatus}
              onChange={(e) => setTargetStatus(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
            >
              {ALLOWED_TARGET_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label} ({s.value})
                </option>
              ))}
            </select>
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <label htmlFor="transition-reason" className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Documented Justification <span className="text-rose-500">*</span>
              </label>
              <span className="text-xs text-slate-400">Min 10 characters</span>
            </div>
            <textarea
              id="transition-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="State the factual basis and evidentiary rationale for this lifecycle transition..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              required
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" size="sm" type="button" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isSubmitting}>
              Confirm Transition
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

// ─── Assign Investigator Dialog ────────────────────────────────────────────

interface AssignInvestigatorModalProps {
  caseItem: CaseRead;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updated: CaseRead) => void;
}

export const AssignInvestigatorModal: React.FC<AssignInvestigatorModalProps> = ({
  caseItem,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [investigatorId, setInvestigatorId] = useState('');
  const [reason, setReason] = useState('');
  const [isOverride, setIsOverride] = useState(false);
  const [overrideJustification, setOverrideJustification] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const cleanId = investigatorId.trim();
    if (!cleanId) {
      setError('Valid Investigator UUID is required.');
      return;
    }

    if (isOverride && !overrideJustification.trim()) {
      setError('Supervisor override requires a documented factual justification.');
      return;
    }

    setIsSubmitting(true);
    try {
      const updated = await assignCase(caseItem.id, {
        new_investigator_id: cleanId,
        assignment_reason: reason.trim() || undefined,
        expected_version: caseItem.version_id,
        is_supervisor_override: isOverride,
        override_justification: isOverride ? overrideJustification.trim() : undefined,
      });
      onSuccess(updated);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to assign lead investigator.';
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="assign-title">
      <div className="w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden">
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <h2 id="assign-title" className="text-base font-bold text-slate-900 flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-indigo-600" />
            Assign Lead Investigator
          </h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600 p-1 rounded" aria-label="Close dialog">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && <Alert variant="error">{error}</Alert>}

          <div>
            <label htmlFor="investigator-id" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
              Investigator User ID (UUID) <span className="text-rose-500">*</span>
            </label>
            <input
              id="investigator-id"
              type="text"
              value={investigatorId}
              onChange={(e) => setInvestigatorId(e.target.value)}
              placeholder="e.g. 11111111-2222-3333-4444-555555555555"
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              required
            />
          </div>

          <div>
            <label htmlFor="assign-reason" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
              Assignment Rationale
            </label>
            <textarea
              id="assign-reason"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Operational context for assigning this lead investigator..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
            />
          </div>

          {/* Supervisor Workload Override */}
          <div className="p-3 bg-amber-50/50 border border-amber-200 rounded-lg space-y-2">
            <label className="flex items-center gap-2 text-xs font-semibold text-amber-900 cursor-pointer">
              <input
                type="checkbox"
                checked={isOverride}
                onChange={(e) => setIsOverride(e.target.checked)}
                className="rounded border-amber-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span>Supervisor Workload Capacity Override</span>
            </label>

            {isOverride && (
              <div>
                <label htmlFor="override-justification" className="block text-xs font-semibold text-amber-900 mb-1">
                  Override Justification <span className="text-rose-500">*</span>
                </label>
                <textarea
                  id="override-justification"
                  rows={2}
                  value={overrideJustification}
                  onChange={(e) => setOverrideJustification(e.target.value)}
                  placeholder="Document why case capacity is overridden for this investigator..."
                  className="w-full px-3 py-1.5 text-xs rounded border border-amber-300 bg-white focus:outline-none focus:ring-2 focus:ring-amber-200"
                  required={isOverride}
                />
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" size="sm" type="button" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isSubmitting}>
              Assign Investigator
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

// ─── Submit for Review Dialog ──────────────────────────────────────────────

interface SubmitForReviewModalProps {
  caseItem: CaseRead;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (updated: CaseRead) => void;
}

export const SubmitForReviewModal: React.FC<SubmitForReviewModalProps> = ({
  caseItem,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = reason.trim();
    if (trimmed.length < 10) {
      setError('A formal submission justification of at least 10 characters is required.');
      return;
    }

    setIsSubmitting(true);
    try {
      const updated = await submitCaseForReview(caseItem.id, {
        reason: trimmed,
        expected_version_id: caseItem.version_id,
      });
      onSuccess(updated);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to submit case for supervisor review.';
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="review-submit-title">
      <div className="w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden">
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <h2 id="review-submit-title" className="text-base font-bold text-slate-900 flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-indigo-600" />
            Submit Case for Supervisory Review
          </h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600 p-1 rounded" aria-label="Close dialog">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && <Alert variant="error">{error}</Alert>}

          <p className="text-xs text-slate-600 leading-relaxed">
            Submitting this case transitions status to <strong className="font-mono">PENDING_SUPERVISOR_REVIEW</strong>.
            The case readiness engine will verify that all required investigation findings and evidence links are satisfied.
            Self-approval by lead investigators is strictly prohibited by institutional policy.
          </p>

          <div>
            <div className="flex justify-between items-center mb-1">
              <label htmlFor="submit-reason" className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Submission Justification <span className="text-rose-500">*</span>
              </label>
              <span className="text-xs text-slate-400">Min 10 characters</span>
            </div>
            <textarea
              id="submit-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="State the findings completion and factual justification for supervisory submission..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              required
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" size="sm" type="button" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isSubmitting}>
              Submit for Review
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

// ─── Legal Hold Dialog ─────────────────────────────────────────────────────

interface LegalHoldModalProps {
  caseId: string;
  evidenceId: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export const PlaceLegalHoldModal: React.FC<LegalHoldModalProps> = ({
  caseId,
  evidenceId,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = reason.trim();
    if (trimmed.length < 10) {
      setError('A formal legal hold rationale of at least 10 characters is required.');
      return;
    }

    setIsSubmitting(true);
    try {
      await placeLegalHold(caseId, evidenceId, {
        reason: trimmed,
        notes: notes.trim() || undefined,
      });
      onSuccess();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to place legal hold.';
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="hold-title">
      <div className="w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden">
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <h2 id="hold-title" className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Lock className="h-4 w-4 text-purple-600" />
            Place Formal Legal Hold on Evidence
          </h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600 p-1 rounded" aria-label="Close dialog">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && <Alert variant="error">{error}</Alert>}

          <p className="text-xs text-slate-600 leading-relaxed">
            Placing a formal legal hold strictly prohibits deletion, alteration, or unlinking of this evidence attachment across all incident and case lifecycles.
          </p>

          <div>
            <div className="flex justify-between items-center mb-1">
              <label htmlFor="hold-reason" className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Legal Hold Rationale <span className="text-rose-500">*</span>
              </label>
              <span className="text-xs text-slate-400">Min 10 characters</span>
            </div>
            <textarea
              id="hold-reason"
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="State the formal legal, regulatory, or disciplinary hold requirement..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              required
            />
          </div>

          <div>
            <label htmlFor="hold-notes" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
              Supplementary Notes
            </label>
            <input
              id="hold-notes"
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Litigation hold notice ref #2026-LIT-089"
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" size="sm" type="button" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isSubmitting}>
              Enforce Legal Hold
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
