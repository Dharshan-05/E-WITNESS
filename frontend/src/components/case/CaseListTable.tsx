import React, { useState } from 'react';
import {
  Search,
  Filter,
  Lock,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
  Calendar,
  AlertCircle,
  RefreshCw,
  FolderLock,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import type { CaseRead, CaseStatus, CasePriority } from '../../types/case';

interface CaseListTableProps {
  cases: CaseRead[];
  total: number;
  limit: number;
  offset: number;
  isLoading: boolean;
  error: string | null;
  onRefresh: () => void;
  onSelectCase: (caseItem: CaseRead) => void;
  onFilterChange: (filters: {
    search?: string;
    status?: string;
    priority?: string;
    is_legal_hold?: boolean;
    offset?: number;
  }) => void;
}

export const CaseListTable: React.FC<CaseListTableProps> = ({
  cases,
  total,
  limit,
  offset,
  isLoading,
  error,
  onRefresh,
  onSelectCase,
  onFilterChange,
}) => {
  const [searchInput, setSearchInput] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [priorityFilter, setPriorityFilter] = useState<string>('');
  const [legalHoldFilter, setLegalHoldFilter] = useState<string>('');

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onFilterChange({
      search: searchInput.trim() || undefined,
      status: statusFilter || undefined,
      priority: priorityFilter || undefined,
      is_legal_hold: legalHoldFilter === 'true' ? true : legalHoldFilter === 'false' ? false : undefined,
      offset: 0,
    });
  };

  const handleStatusChange = (val: string) => {
    setStatusFilter(val);
    onFilterChange({
      search: searchInput.trim() || undefined,
      status: val || undefined,
      priority: priorityFilter || undefined,
      is_legal_hold: legalHoldFilter === 'true' ? true : legalHoldFilter === 'false' ? false : undefined,
      offset: 0,
    });
  };

  const handlePriorityChange = (val: string) => {
    setPriorityFilter(val);
    onFilterChange({
      search: searchInput.trim() || undefined,
      status: statusFilter || undefined,
      priority: val || undefined,
      is_legal_hold: legalHoldFilter === 'true' ? true : legalHoldFilter === 'false' ? false : undefined,
      offset: 0,
    });
  };

  const handleHoldChange = (val: string) => {
    setLegalHoldFilter(val);
    onFilterChange({
      search: searchInput.trim() || undefined,
      status: statusFilter || undefined,
      priority: priorityFilter || undefined,
      is_legal_hold: val === 'true' ? true : val === 'false' ? false : undefined,
      offset: 0,
    });
  };

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));

  const handlePrevPage = () => {
    if (offset > 0) {
      onFilterChange({ offset: Math.max(0, offset - limit) });
    }
  };

  const handleNextPage = () => {
    if (offset + limit < total) {
      onFilterChange({ offset: offset + limit });
    }
  };

  const getStatusBadgeVariant = (status: CaseStatus): 'default' | 'primary' | 'success' | 'warning' | 'danger' => {
    switch (status) {
      case 'open':
      case 'under_investigation':
        return 'primary';
      case 'pending_review':
      case 'pending_supervisor_review':
        return 'warning';
      case 'resolved':
      case 'closed':
        return 'success';
      case 'suspended':
        return 'default';
      case 'reopened':
        return 'danger';
      default:
        return 'default';
    }
  };

  const getPriorityBadgeVariant = (priority: CasePriority): 'default' | 'primary' | 'warning' | 'danger' => {
    switch (priority) {
      case 'critical':
        return 'danger';
      case 'high':
        return 'warning';
      case 'medium':
        return 'primary';
      default:
        return 'default';
    }
  };

  return (
    <div className="space-y-4" data-testid="case-list-table">
      {/* Search and Filters Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-3">
        <form onSubmit={handleSearchSubmit} className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by case reference, title, or summary..."
              className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              data-testid="case-search-input"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => handleStatusChange(e.target.value)}
              className="px-2.5 py-2 text-xs rounded-lg border border-slate-300 bg-white text-slate-700"
              aria-label="Filter by Status"
            >
              <option value="">All Statuses</option>
              <option value="draft">Draft</option>
              <option value="open">Open</option>
              <option value="under_investigation">Under Investigation</option>
              <option value="pending_review">Pending Review</option>
              <option value="pending_supervisor_review">Supervisor Review</option>
              <option value="suspended">Suspended</option>
              <option value="resolved">Resolved</option>
              <option value="closed">Closed</option>
              <option value="reopened">Reopened</option>
            </select>

            <select
              value={priorityFilter}
              onChange={(e) => handlePriorityChange(e.target.value)}
              className="px-2.5 py-2 text-xs rounded-lg border border-slate-300 bg-white text-slate-700"
              aria-label="Filter by Priority"
            >
              <option value="">All Priorities</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>

            <select
              value={legalHoldFilter}
              onChange={(e) => handleHoldChange(e.target.value)}
              className="px-2.5 py-2 text-xs rounded-lg border border-slate-300 bg-white text-slate-700"
              aria-label="Filter by Legal Hold"
            >
              <option value="">Legal Hold (All)</option>
              <option value="true">Under Hold Only</option>
              <option value="false">No Active Hold</option>
            </select>

            <Button variant="outline" size="sm" type="submit">
              <Filter className="h-3.5 w-3.5 mr-1" />
              Filter
            </Button>
          </div>
        </form>
      </div>

      {/* Error state */}
      {error && (
        <Card className="border-rose-200 bg-rose-50/50">
          <div className="p-4 flex items-center justify-between text-xs text-rose-800">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-rose-600 shrink-0" />
              <span>{error}</span>
            </div>
            <Button variant="ghost" size="sm" onClick={onRefresh}>
              <RefreshCw className="h-3.5 w-3.5 mr-1" />
              Retry
            </Button>
          </div>
        </Card>
      )}

      {/* Table Container */}
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden shadow-xs">
        {isLoading ? (
          <div className="p-6 space-y-3" data-testid="case-table-loading">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : cases.length === 0 ? (
          <div className="p-8">
            <EmptyState
              icon={<FolderLock className="h-8 w-8 text-slate-400" />}
              title="No Investigation Cases Found"
              description="No investigation cases match your current query or department scope."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3">Case Reference</th>
                  <th scope="col" className="px-4 py-3">Title & Summary</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                  <th scope="col" className="px-4 py-3">Priority</th>
                  <th scope="col" className="px-4 py-3">Department / Lead</th>
                  <th scope="col" className="px-4 py-3">Counts</th>
                  <th scope="col" className="px-4 py-3">Created</th>
                  <th scope="col" className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {cases.map((caseItem) => (
                  <tr
                    key={caseItem.id}
                    className="hover:bg-slate-50/70 transition-colors cursor-pointer"
                    onClick={() => onSelectCase(caseItem)}
                    data-testid={`case-row-${caseItem.id}`}
                  >
                    <td className="px-4 py-3 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                          {caseItem.reference_number}
                        </span>
                        {caseItem.is_legal_hold && (
                          <span title="Under Active Legal Hold">
                            <Lock className="h-3.5 w-3.5 text-purple-600" />
                          </span>
                        )}
                      </div>
                    </td>

                    <td className="px-4 py-3 max-w-xs">
                      <div className="font-medium text-slate-900 truncate" title={caseItem.title}>
                        {caseItem.title}
                      </div>
                      <div className="text-xs text-slate-400 truncate line-clamp-1" title={caseItem.summary}>
                        {caseItem.summary}
                      </div>
                    </td>

                    <td className="px-4 py-3 whitespace-nowrap">
                      <Badge variant={getStatusBadgeVariant(caseItem.status)} size="sm">
                        {caseItem.status.replace(/_/g, ' ').toUpperCase()}
                      </Badge>
                    </td>

                    <td className="px-4 py-3 whitespace-nowrap">
                      <Badge variant={getPriorityBadgeVariant(caseItem.priority)} size="sm">
                        {caseItem.priority.toUpperCase()}
                      </Badge>
                    </td>

                    <td className="px-4 py-3 whitespace-nowrap text-xs">
                      <div className="text-slate-800 font-medium">
                        {caseItem.department_name || caseItem.department_id.slice(0, 8) + '…'}
                      </div>
                      <div className="text-slate-400">
                        {caseItem.lead_investigator_name || (caseItem.lead_investigator_id ? `Inv: ${caseItem.lead_investigator_id.slice(0, 8)}…` : 'Unassigned')}
                      </div>
                    </td>

                    <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500 font-mono">
                      <span>{caseItem.incidents_count} inc</span> · <span>{caseItem.evidence_count} evi</span>
                    </td>

                    <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                      <span className="flex items-center gap-1">
                        <Calendar className="h-3 w-3 text-slate-400" />
                        {new Date(caseItem.created_at).toLocaleDateString()}
                      </span>
                    </td>

                    <td className="px-4 py-3 whitespace-nowrap text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectCase(caseItem);
                        }}
                        className="text-xs text-indigo-600 hover:text-indigo-800"
                        aria-label={`Open dossier for case ${caseItem.reference_number}`}
                      >
                        <FolderOpen className="h-3.5 w-3.5 mr-1" />
                        Dossier
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Bar */}
        {!isLoading && cases.length > 0 && (
          <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500">
            <div>
              Showing <span className="font-semibold text-slate-700">{offset + 1}</span> to{' '}
              <span className="font-semibold text-slate-700">
                {Math.min(offset + limit, total)}
              </span>{' '}
              of <span className="font-semibold text-slate-700">{total}</span> cases
            </div>

            <div className="flex items-center gap-2">
              <span>
                Page {currentPage} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={handlePrevPage}
                disabled={offset === 0}
                aria-label="Previous page"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleNextPage}
                disabled={offset + limit >= total}
                aria-label="Next page"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
