import React, { useState } from 'react';
import { X, PlusCircle, AlertTriangle } from 'lucide-react';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import { createCase } from '../../api/case';
import type { CaseRead, CasePriority } from '../../types/case';

interface CaseCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (newCase: CaseRead) => void;
  initialIncidentId?: string | null;
}

const PRIORITIES: { value: CasePriority; label: string }[] = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
];

export const CaseCreateModal: React.FC<CaseCreateModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  initialIncidentId,
}) => {
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [priority, setPriority] = useState<CasePriority>('medium');
  const [leadInvestigatorId, setLeadInvestigatorId] = useState('');
  const [incidentId, setIncidentId] = useState(initialIncidentId || '');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const cleanTitle = title.trim();
    if (cleanTitle.length < 5) {
      setError('Case title must be at least 5 characters.');
      return;
    }
    if (cleanTitle.length > 200) {
      setError('Case title cannot exceed 200 characters.');
      return;
    }

    const cleanSummary = summary.trim();
    if (cleanSummary.length < 10) {
      setError('Case summary must be at least 10 characters.');
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await createCase({
        title: cleanTitle,
        summary: cleanSummary,
        priority,
        lead_investigator_id: leadInvestigatorId.trim() || undefined,
        initial_incident_id: incidentId.trim() || undefined,
      });

      onSuccess(created);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create investigation case.';
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="case-create-title"
    >
      <div className="w-full max-w-xl bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <h2 id="case-create-title" className="text-base font-bold text-slate-900 flex items-center gap-2">
            <PlusCircle className="h-4 w-4 text-indigo-600" />
            Initiate New Investigation Case
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded"
            aria-label="Close dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && <Alert variant="error">{error}</Alert>}

          <div>
            <div className="flex justify-between items-center mb-1">
              <label htmlFor="case-title" className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Case Title <span className="text-rose-500">*</span>
              </label>
              <span className="text-xs text-slate-400">{title.length}/200</span>
            </div>
            <input
              id="case-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Investigation of Unauthorized Access in North Annex"
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              required
            />
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <label htmlFor="case-summary" className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Factual Case Summary <span className="text-rose-500">*</span>
              </label>
              <span className="text-xs text-slate-400">Min 10 characters</span>
            </div>
            <textarea
              id="case-summary"
              rows={4}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="Summarize the core facts, allegations, timeline, and scope of this formal investigation..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              required
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="case-priority" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                Priority Tier
              </label>
              <select
                id="case-priority"
                value={priority}
                onChange={(e) => setPriority(e.target.value as CasePriority)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              >
                {PRIORITIES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="lead-investigator" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                Lead Investigator ID (Optional)
              </label>
              <input
                id="lead-investigator"
                type="text"
                value={leadInvestigatorId}
                onChange={(e) => setLeadInvestigatorId(e.target.value)}
                placeholder="User UUID"
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              />
            </div>
          </div>

          <div>
            <label htmlFor="initial-incident" className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
              Initial Linked Incident ID (Optional)
            </label>
            <input
              id="initial-incident"
              type="text"
              value={incidentId}
              onChange={(e) => setIncidentId(e.target.value)}
              placeholder="Incident UUID"
              className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
            />
          </div>

          {/* Institutional Statutory Notice */}
          <div className="flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2.5">
            <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
            <span>
              Case initiation assigns an immutable reference identifier (`CASE-YYYY-XXXXXXXX`) and enforces departmental scope isolation.
            </span>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" size="sm" type="button" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" isLoading={isSubmitting}>
              Create Case File
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
