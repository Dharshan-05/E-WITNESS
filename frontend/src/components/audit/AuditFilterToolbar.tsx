import React, { useState } from 'react';
import { Search, RotateCcw, ShieldCheck, Download } from 'lucide-react';
import { Button } from '../ui/Button';
import type { AuditSearchFilterParams } from '../../types/audit';

export interface AuditFilterToolbarProps {
  filters: AuditSearchFilterParams;
  onApplyFilters: (filters: AuditSearchFilterParams) => void;
  onResetFilters: () => void;
  onOpenVerify: () => void;
  onOpenExport: () => void;
  isLoading?: boolean;
}

export const AuditFilterToolbar: React.FC<AuditFilterToolbarProps> = ({
  filters,
  onApplyFilters,
  onResetFilters,
  onOpenVerify,
  onOpenExport,
  isLoading = false,
}) => {
  const [action, setAction] = useState(filters.action || '');
  const [actorId, setActorId] = useState(filters.actor_id || '');
  const [targetType, setTargetType] = useState(filters.target_type || '');
  const [targetId, setTargetId] = useState(filters.target_id || '');
  const [outcome, setOutcome] = useState(filters.outcome || '');
  const [startTime, setStartTime] = useState(filters.start_time || '');
  const [endTime, setEndTime] = useState(filters.end_time || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onApplyFilters({
      action: action.trim() || undefined,
      actor_id: actorId.trim() || undefined,
      target_type: targetType.trim() || undefined,
      target_id: targetId.trim() || undefined,
      outcome: outcome || undefined,
      start_time: startTime || undefined,
      end_time: endTime || undefined,
      page: 1,
      page_size: filters.page_size || 50,
    });
  };

  const handleReset = () => {
    setAction('');
    setActorId('');
    setTargetType('');
    setTargetId('');
    setOutcome('');
    setStartTime('');
    setEndTime('');
    onResetFilters();
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-3 border-b border-slate-100">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Ledger Search & Filter Bounds</h3>
          <p className="text-xs text-slate-500">Query immutable, tamper-evident security audit entries with strict department scoping.</p>
        </div>
        <div className="flex items-center gap-2 self-end sm:self-auto">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onOpenVerify}
            className="flex items-center gap-1.5 text-xs text-indigo-700 border-indigo-200 hover:bg-indigo-50"
          >
            <ShieldCheck className="h-4 w-4" />
            <span>Verify Integrity</span>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onOpenExport}
            className="flex items-center gap-1.5 text-xs text-slate-700 hover:bg-slate-50"
          >
            <Download className="h-4 w-4" />
            <span>Export Ledger</span>
          </Button>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          <div>
            <label htmlFor="filter-action" className="block font-medium text-slate-700 mb-1">
              Audit Action
            </label>
            <input
              id="filter-action"
              type="text"
              placeholder="e.g. auth:login:success"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="filter-actor" className="block font-medium text-slate-700 mb-1">
              Actor ID (UUID)
            </label>
            <input
              id="filter-actor"
              type="text"
              placeholder="Filter by initiator UUID"
              value={actorId}
              onChange={(e) => setActorId(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
            />
          </div>

          <div>
            <label htmlFor="filter-target-type" className="block font-medium text-slate-700 mb-1">
              Target Classification
            </label>
            <select
              id="filter-target-type"
              value={targetType}
              onChange={(e) => setTargetType(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
            >
              <option value="">All Targets</option>
              <option value="incident">Incident</option>
              <option value="evidence">Evidence</option>
              <option value="case">Investigation Case</option>
              <option value="user">User Identity</option>
              <option value="department">Department</option>
              <option value="system">System Configuration</option>
              <option value="session">Authentication Session</option>
              <option value="ai_job">AI Job</option>
            </select>
          </div>

          <div>
            <label htmlFor="filter-outcome" className="block font-medium text-slate-700 mb-1">
              Outcome
            </label>
            <select
              id="filter-outcome"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white"
            >
              <option value="">All Outcomes</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
              <option value="denied">Access Denied</option>
            </select>
          </div>

          <div>
            <label htmlFor="filter-target-id" className="block font-medium text-slate-700 mb-1">
              Target ID
            </label>
            <input
              id="filter-target-id"
              type="text"
              placeholder="e.g. INC-2026-0001"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="filter-start-time" className="block font-medium text-slate-700 mb-1">
              From Timestamp (UTC)
            </label>
            <input
              id="filter-start-time"
              type="datetime-local"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="filter-end-time" className="block font-medium text-slate-700 mb-1">
              To Timestamp (UTC)
            </label>
            <input
              id="filter-end-time"
              type="datetime-local"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="flex items-end gap-2">
            <Button
              type="submit"
              size="sm"
              isLoading={isLoading}
              className="flex-1 flex items-center justify-center gap-1.5 text-xs"
            >
              <Search className="h-3.5 w-3.5" />
              <span>Apply Filters</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleReset}
              className="flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900"
              title="Reset Filters"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Reset</span>
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
};
