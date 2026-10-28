import React from 'react';
import { clsx } from 'clsx';
import { UserCheck, Inbox, ShieldAlert, FolderLock } from 'lucide-react';
import type { ReviewerWorkloadSummaryRead } from '../../types/analytics';
import { Badge } from '../ui/Badge';

export interface WorkloadTableProps {
  data: ReviewerWorkloadSummaryRead | null;
  loading?: boolean;
  className?: string;
}

export const WorkloadTable: React.FC<WorkloadTableProps> = ({
  data,
  loading = false,
  className,
}) => {
  if (loading) {
    return (
      <div className={clsx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm animate-pulse', className)}>
        <div className="h-5 w-48 bg-slate-200 rounded mb-4" />
        <div className="space-y-3">
          <div className="h-10 w-full bg-slate-100 rounded" />
          <div className="h-10 w-full bg-slate-100 rounded" />
          <div className="h-10 w-full bg-slate-100 rounded" />
        </div>
      </div>
    );
  }

  if (!data || data.total_reviewers === 0) {
    return (
      <div className={clsx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm', className)}>
        <h4 className="text-sm font-bold text-slate-900 mb-2">Reviewer & Investigator Workloads</h4>
        <div className="flex h-36 flex-col items-center justify-center text-center text-slate-400">
          <Inbox className="h-8 w-8 mb-2 stroke-1" aria-hidden="true" />
          <p className="text-xs">No active investigator workload profiles returned for this scope.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={clsx('rounded-xl border border-slate-200 bg-white p-5 shadow-sm flex flex-col', className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h4 className="text-sm font-bold text-slate-900">Reviewer & Investigator Workloads</h4>
          <p className="text-xs text-slate-500 mt-0.5">
            Active caseloads, queue assignments, and pending human oversight tasks.
          </p>
        </div>

        {/* Backlog / Unassigned badges */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50/70 px-2.5 py-1 text-xs font-semibold text-amber-900">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-600" aria-hidden="true" />
            <span>Unassigned Incidents:</span>
            <span className="font-mono">{data.unassigned_incidents_count}</span>
          </div>

          <div className="flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50/70 px-2.5 py-1 text-xs font-semibold text-indigo-900">
            <FolderLock className="h-3.5 w-3.5 text-indigo-600" aria-hidden="true" />
            <span>Unassigned Cases:</span>
            <span className="font-mono">{data.unassigned_cases_count}</span>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-left text-xs" aria-label="Reviewer workload statistics">
          <thead className="bg-slate-50 font-semibold text-slate-700">
            <tr>
              <th scope="col" className="px-3 py-2.5">Investigator / Reviewer</th>
              <th scope="col" className="px-3 py-2.5 text-center">Active Cases</th>
              <th scope="col" className="px-3 py-2.5 text-center">Assigned Incidents</th>
              <th scope="col" className="px-3 py-2.5 text-center">Pending AI Reviews</th>
              <th scope="col" className="px-3 py-2.5 text-center">Completed AI Reviews</th>
              <th scope="col" className="px-3 py-2.5 text-center">Completed Case Reviews</th>
              <th scope="col" className="px-3 py-2.5 text-right">Caseload Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {data.reviewers.map((reviewer) => {
              const isHeavy = reviewer.active_cases_count >= 5;
              const hasPending = reviewer.pending_ai_segment_reviews_count > 0;

              return (
                <tr key={reviewer.reviewer_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600 font-bold text-xs">
                        <UserCheck className="h-3.5 w-3.5" aria-hidden="true" />
                      </div>
                      <div className="flex flex-col">
                        <span className="font-semibold text-slate-900">{reviewer.reviewer_name}</span>
                        <span className="text-[11px] text-slate-500 font-mono">{reviewer.reviewer_email}</span>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-center font-mono font-semibold text-slate-900">
                    {reviewer.active_cases_count}
                  </td>
                  <td className="px-3 py-2 text-center font-mono text-slate-700">
                    {reviewer.assigned_incidents_count}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span
                      className={clsx(
                        'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-mono font-semibold',
                        hasPending ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600'
                      )}
                    >
                      {reviewer.pending_ai_segment_reviews_count}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center font-mono text-slate-600">
                    {reviewer.completed_ai_segment_reviews_count}
                  </td>
                  <td className="px-3 py-2 text-center font-mono text-slate-600">
                    {reviewer.completed_case_reviews_count}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Badge variant={isHeavy ? 'warning' : 'success'} size="sm">
                      {isHeavy ? 'Heavy Caseload' : 'Optimal'}
                    </Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
