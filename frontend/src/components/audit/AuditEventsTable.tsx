import React from 'react';
import { Eye, ChevronLeft, ChevronRight, Hash } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import type { SecurityAuditEvent } from '../../types/audit';

export interface AuditEventsTableProps {
  events: SecurityAuditEvent[];
  totalItems: number;
  currentPage: number;
  pageSize: number;
  totalPages: number;
  isLoading?: boolean;
  onSelectEvent: (event: SecurityAuditEvent) => void;
  onPageChange: (newPage: number) => void;
}

export const AuditEventsTable: React.FC<AuditEventsTableProps> = ({
  events,
  totalItems,
  currentPage,
  pageSize,
  totalPages,
  isLoading = false,
  onSelectEvent,
  onPageChange,
}) => {
  const getOutcomeBadge = (outcome: string) => {
    switch (outcome?.toLowerCase()) {
      case 'success':
        return <Badge variant="success" size="sm">Success</Badge>;
      case 'failure':
        return <Badge variant="danger" size="sm">Failure</Badge>;
      case 'denied':
        return <Badge variant="warning" size="sm">Denied</Badge>;
      default:
        return <Badge variant="default" size="sm">{outcome}</Badge>;
    }
  };

  const formatDate = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    } catch {
      return isoString;
    }
  };

  if (isLoading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
        <Skeleton className="h-6 w-48 mb-4" />
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <EmptyState
          title="No Audit Entries Found"
          description="No security audit events matched your search criteria and institutional department scoping parameters."
        />
      </div>
    );
  }

  const startEntry = (currentPage - 1) * pageSize + 1;
  const endEntry = Math.min(currentPage * pageSize, totalItems);

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/75 text-slate-600 font-semibold uppercase tracking-wider">
              <th className="py-3 px-4 w-16"># Seq</th>
              <th className="py-3 px-4 w-44">Timestamp</th>
              <th className="py-3 px-4">Action</th>
              <th className="py-3 px-4">Actor</th>
              <th className="py-3 px-4">Target</th>
              <th className="py-3 px-4 w-24">Outcome</th>
              <th className="py-3 px-4 w-32">Event Hash</th>
              <th className="py-3 px-4 w-20 text-right">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {events.map((event) => (
              <tr
                key={event.id}
                className="hover:bg-slate-50/60 transition-colors cursor-pointer group"
                onClick={() => onSelectEvent(event)}
              >
                <td className="py-3 px-4 font-mono font-bold text-slate-800">
                  <span className="flex items-center gap-1">
                    <Hash className="h-3 w-3 text-slate-400" />
                    {event.sequence_number}
                  </span>
                </td>
                <td className="py-3 px-4 font-mono text-slate-600 whitespace-nowrap">
                  {formatDate(event.created_at)}
                </td>
                <td className="py-3 px-4">
                  <span className="font-semibold text-slate-900 group-hover:text-indigo-600 transition-colors">
                    {event.action}
                  </span>
                </td>
                <td className="py-3 px-4">
                  <div className="flex flex-col">
                    <span className="font-mono text-slate-700 truncate max-w-[120px]" title={event.actor_id || 'System'}>
                      {event.actor_id ? `${event.actor_id.substring(0, 8)}...` : 'System'}
                    </span>
                    {event.actor_role && (
                      <span className="text-[10px] text-slate-400">{event.actor_role}</span>
                    )}
                  </div>
                </td>
                <td className="py-3 px-4">
                  <div className="flex flex-col">
                    <span className="font-medium text-slate-800">{event.target_type}</span>
                    <span className="font-mono text-[11px] text-slate-500 truncate max-w-[140px]" title={event.target_id}>
                      {event.target_id}
                    </span>
                  </div>
                </td>
                <td className="py-3 px-4 whitespace-nowrap">
                  {getOutcomeBadge(event.outcome)}
                </td>
                <td className="py-3 px-4 font-mono text-[11px] text-slate-500" title={event.event_hash}>
                  {event.event_hash.substring(0, 10)}...
                </td>
                <td className="py-3 px-4 text-right">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectEvent(event);
                    }}
                    className="h-7 w-7 p-0 text-slate-500 hover:text-indigo-600 hover:bg-slate-100 rounded-md"
                    title="View Full Record"
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50/50 text-xs text-slate-600">
        <div>
          Showing <span className="font-semibold text-slate-900">{startEntry}</span> to{' '}
          <span className="font-semibold text-slate-900">{endEntry}</span> of{' '}
          <span className="font-semibold text-slate-900">{totalItems}</span> ledger records
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={currentPage <= 1}
            onClick={() => onPageChange(currentPage - 1)}
            className="flex items-center gap-1 text-xs"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span>Previous</span>
          </Button>

          <span className="font-medium px-2">
            Page {currentPage} of {totalPages || 1}
          </span>

          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(currentPage + 1)}
            className="flex items-center gap-1 text-xs"
          >
            <span>Next</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
};
