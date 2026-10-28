import React, { useState, useEffect, useCallback } from 'react';
import {
  Search,
  RotateCcw,
  Eye,
  ChevronLeft,
  ChevronRight,
  ShieldAlert,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import { Alert } from '../ui/Alert';
import {
  type IncidentRead,
  type QueueParams,
  INCIDENT_CATEGORIES,
  INCIDENT_SEVERITIES,
} from '../../types/incident';
import { getReviewQueue } from '../../api/incident';
import { IncidentDetailModal } from './IncidentDetailModal';
import { ApiError } from '../../types/api';

export const ReviewQueueTable: React.FC = () => {
  // State
  const [incidents, setIncidents] = useState<IncidentRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Pagination
  const [page, setPage] = useState(1);
  const [pageSize] = useState(15);
  const [totalPages, setTotalPages] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [hasPrev, setHasPrev] = useState(false);

  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<string>('');
  const [severity, setSeverity] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [assignmentStatus, setAssignmentStatus] = useState<string>('');

  // Inspection Modal State
  const [selectedIncident, setSelectedIncident] = useState<IncidentRead | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Fetch Queue Data
  const fetchQueue = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params: QueueParams = {
        page,
        page_size: pageSize,
        sort_by: 'created_at',
        sort_order: 'desc',
      };
      if (search.trim()) params.search = search.trim();
      if (category) params.category = category;
      if (severity) params.severity = severity;
      if (status) params.status = status;
      if (assignmentStatus) params.assignment_status = assignmentStatus;

      const response = await getReviewQueue(params);
      setIncidents(response.items || []);

      if (response.pagination) {
        setTotalPages(response.pagination.total_pages);
        setTotalItems(response.pagination.total_items);
        setHasNext(response.pagination.has_next);
        setHasPrev(response.pagination.has_prev);
      } else {
        setTotalItems(response.items?.length || 0);
        setTotalPages(1);
        setHasNext(false);
        setHasPrev(false);
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to load review queue. Please verify permissions or network connectivity.');
      }
    } finally {
      setIsLoading(false);
    }
  }, [page, pageSize, search, category, severity, status, assignmentStatus]);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  const handleResetFilters = () => {
    setSearch('');
    setCategory('');
    setSeverity('');
    setStatus('');
    setAssignmentStatus('');
    setPage(1);
  };

  const handleInspect = (incident: IncidentRead) => {
    setSelectedIncident(incident);
    setIsModalOpen(true);
  };

  const getSeverityBadgeVariant = (sev: string): 'default' | 'primary' | 'warning' | 'danger' => {
    switch (sev?.toLowerCase()) {
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

  const getStatusBadgeVariant = (stat: string): 'default' | 'primary' | 'success' | 'warning' | 'danger' => {
    switch (stat?.toLowerCase()) {
      case 'submitted':
        return 'primary';
      case 'triaged':
        return 'warning';
      case 'under_investigation':
        return 'danger';
      case 'closed':
        return 'success';
      default:
        return 'default';
    }
  };

  return (
    <div className="space-y-4">
      {/* Search & Filter Toolbar */}
      <div className="bg-white p-4 rounded-lg border border-slate-200 shadow-xs space-y-3">
        <div className="flex flex-col md:flex-row gap-3 items-stretch md:items-center justify-between">
          {/* Search Box */}
          <div className="relative flex-1">
            <Search className="h-4 w-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
            <input
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search by title, narrative keywords, or reference ID (INC-...)"
              className="w-full pl-9 pr-3.5 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:border-indigo-600 focus:ring-1 focus:ring-indigo-600"
            />
          </div>

          {/* Action Buttons */}
          <div className="flex items-center space-x-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={handleResetFilters}
              leftIcon={<RotateCcw className="h-3.5 w-3.5" />}
            >
              Reset
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchQueue}
              isLoading={isLoading}
            >
              Refresh
            </Button>
          </div>
        </div>

        {/* Filter Selects */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-slate-100 text-xs">
          {/* Category Filter */}
          <div>
            <label htmlFor="filter-category" className="block text-slate-500 font-medium mb-1">
              Category
            </label>
            <select
              id="filter-category"
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
              className="w-full px-2.5 py-1.5 rounded-md border border-slate-300 bg-white text-slate-700 focus:outline-none focus:border-indigo-600"
            >
              <option value="">All Categories</option>
              {INCIDENT_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          {/* Severity Filter */}
          <div>
            <label htmlFor="filter-severity" className="block text-slate-500 font-medium mb-1">
              Severity
            </label>
            <select
              id="filter-severity"
              value={severity}
              onChange={(e) => {
                setSeverity(e.target.value);
                setPage(1);
              }}
              className="w-full px-2.5 py-1.5 rounded-md border border-slate-300 bg-white text-slate-700 focus:outline-none focus:border-indigo-600"
            >
              <option value="">All Severities</option>
              {INCIDENT_SEVERITIES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          {/* Status Filter */}
          <div>
            <label htmlFor="filter-status" className="block text-slate-500 font-medium mb-1">
              Status
            </label>
            <select
              id="filter-status"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              className="w-full px-2.5 py-1.5 rounded-md border border-slate-300 bg-white text-slate-700 focus:outline-none focus:border-indigo-600"
            >
              <option value="">All Statuses</option>
              <option value="submitted">Submitted</option>
              <option value="triaged">Triaged</option>
              <option value="under_investigation">Under Investigation</option>
              <option value="closed">Closed</option>
              <option value="dismissed">Dismissed</option>
            </select>
          </div>

          {/* Assignment Status Filter */}
          <div>
            <label htmlFor="filter-assignment" className="block text-slate-500 font-medium mb-1">
              Assignment
            </label>
            <select
              id="filter-assignment"
              value={assignmentStatus}
              onChange={(e) => {
                setAssignmentStatus(e.target.value);
                setPage(1);
              }}
              className="w-full px-2.5 py-1.5 rounded-md border border-slate-300 bg-white text-slate-700 focus:outline-none focus:border-indigo-600"
            >
              <option value="">All Assignment States</option>
              <option value="unassigned">Unassigned</option>
              <option value="assigned">Assigned</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="completed">Completed</option>
            </select>
          </div>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <Alert variant="error" title="Queue Error">
          {error}
        </Alert>
      )}

      {/* Table Container */}
      <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
        {isLoading ? (
          <div className="p-6 space-y-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : incidents.length === 0 ? (
          <div className="py-12">
            <EmptyState
              icon={<ShieldAlert className="h-8 w-8 text-slate-400" />}
              title="No Incidents Match Queue Filters"
              description="No incident reports match your current filter criteria or scope."
              action={
                <Button variant="outline" size="sm" onClick={handleResetFilters}>
                  Clear Filters
                </Button>
              }
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 font-semibold text-slate-700 uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-4 py-3">Reference ID</th>
                  <th scope="col" className="px-4 py-3">Title & Classification</th>
                  <th scope="col" className="px-4 py-3">Severity</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                  <th scope="col" className="px-4 py-3">Assignment</th>
                  <th scope="col" className="px-4 py-3">Occurred At</th>
                  <th scope="col" className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {incidents.map((inc) => (
                  <tr key={inc.id} className="hover:bg-slate-50/80 transition-colors">
                    {/* Ref Number */}
                    <td className="px-4 py-3 font-mono font-bold text-indigo-700 whitespace-nowrap">
                      {inc.reference_number}
                    </td>

                    {/* Title & Category */}
                    <td className="px-4 py-3 max-w-xs sm:max-w-md">
                      <div className="font-semibold text-slate-900 truncate">{inc.title}</div>
                      <div className="text-[11px] text-slate-500 capitalize flex items-center space-x-1.5 mt-0.5">
                        <span>{inc.category.replace(/_/g, ' ')}</span>
                        <span>•</span>
                        <span className="truncate">{inc.location}</span>
                      </div>
                    </td>

                    {/* Severity */}
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Badge variant={getSeverityBadgeVariant(inc.severity)} size="sm">
                        {inc.severity.toUpperCase()}
                      </Badge>
                    </td>

                    {/* Status */}
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Badge variant={getStatusBadgeVariant(inc.status)} size="sm">
                        {inc.status.toUpperCase()}
                      </Badge>
                    </td>

                    {/* Assignment */}
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-medium text-slate-700 capitalize">
                        {inc.assignment_status || 'unassigned'}
                      </span>
                    </td>

                    {/* Occurred At */}
                    <td className="px-4 py-3 whitespace-nowrap text-slate-500">
                      {new Date(inc.occurred_at).toLocaleDateString()}
                    </td>

                    {/* Actions */}
                    <td className="px-4 py-3 whitespace-nowrap text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleInspect(inc)}
                        leftIcon={<Eye className="h-3.5 w-3.5" />}
                      >
                        Inspect
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Footer */}
        {!isLoading && incidents.length > 0 && (
          <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-600">
            <div>
              Showing <span className="font-medium">{incidents.length}</span> of{' '}
              <span className="font-medium">{totalItems}</span> incidents (Page {page} of {totalPages})
            </div>
            <div className="flex items-center space-x-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={!hasPrev || page <= 1}
                leftIcon={<ChevronLeft className="h-3.5 w-3.5" />}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={!hasNext || page >= totalPages}
                rightIcon={<ChevronRight className="h-3.5 w-3.5" />}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Detail Inspection Modal */}
      <IncidentDetailModal
        incident={selectedIncident}
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedIncident(null);
        }}
      />
    </div>
  );
};
