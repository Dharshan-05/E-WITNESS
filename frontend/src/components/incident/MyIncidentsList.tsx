import React, { useState, useEffect, useCallback } from 'react';
import { ShieldCheck, Eye, RotateCcw } from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import { Alert } from '../ui/Alert';
import type { IncidentRead } from '../../types/incident';
import { listIncidents } from '../../api/incident';
import { IncidentDetailModal } from './IncidentDetailModal';
import { ApiError } from '../../types/api';

interface MyIncidentsListProps {
  onReportNew?: () => void;
}

export const MyIncidentsList: React.FC<MyIncidentsListProps> = ({ onReportNew }) => {
  const [incidents, setIncidents] = useState<IncidentRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedIncident, setSelectedIncident] = useState<IncidentRead | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const fetchMyReports = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listIncidents({
        page: 1,
        page_size: 50,
        sort_by: 'created_at',
        sort_order: 'desc',
      });
      setIncidents(response.items || []);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to load your reported incidents.');
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMyReports();
  }, [fetchMyReports]);

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

  const handleInspect = (inc: IncidentRead) => {
    setSelectedIncident(inc);
    setIsModalOpen(true);
  };

  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-900">Your Submitted Reports</h2>
          <p className="text-xs text-slate-500">
            Reports submitted under your institutional account and their current triage states.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={fetchMyReports}
          isLoading={isLoading}
          leftIcon={<RotateCcw className="h-3.5 w-3.5" />}
        >
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="error" title="Unable to Load Reports">
          {error}
        </Alert>
      )}

      {/* Content */}
      {isLoading ? (
        <div className="p-6 bg-white border border-slate-200 rounded-lg space-y-3">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : incidents.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-lg py-12">
          <EmptyState
            icon={<ShieldCheck className="h-8 w-8 text-emerald-600" />}
            title="No Incidents Reported"
            description="You have not submitted any incident reports under your account."
            action={
              onReportNew ? (
                <Button variant="primary" size="sm" onClick={onReportNew}>
                  Report an Incident
                </Button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-lg shadow-xs overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 font-semibold text-slate-700 uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-4 py-3">Reference ID</th>
                  <th scope="col" className="px-4 py-3">Title & Classification</th>
                  <th scope="col" className="px-4 py-3">Status</th>
                  <th scope="col" className="px-4 py-3">Occurred At</th>
                  <th scope="col" className="px-4 py-3">Submitted At</th>
                  <th scope="col" className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {incidents.map((inc) => (
                  <tr key={inc.id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="px-4 py-3 font-mono font-bold text-indigo-700 whitespace-nowrap">
                      {inc.reference_number}
                    </td>
                    <td className="px-4 py-3 max-w-sm">
                      <div className="font-semibold text-slate-900 truncate">{inc.title}</div>
                      <div className="text-[11px] text-slate-500 capitalize">{inc.category.replace(/_/g, ' ')}</div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Badge variant={getStatusBadgeVariant(inc.status)} size="sm">
                        {inc.status.toUpperCase()}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-500">
                      {new Date(inc.occurred_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-500">
                      {new Date(inc.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleInspect(inc)}
                        leftIcon={<Eye className="h-3.5 w-3.5" />}
                      >
                        Details
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Detail Modal */}
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
