import React from 'react';
import { Building, Hash, Calendar } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import type { DepartmentListItem } from '../../types/admin';

export interface DepartmentManagementTableProps {
  departments: DepartmentListItem[];
  isLoading?: boolean;
}

export const DepartmentManagementTable: React.FC<DepartmentManagementTableProps> = ({
  departments,
  isLoading = false,
}) => {
  if (isLoading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-3">
        <Skeleton className="h-6 w-48 mb-4" />
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (departments.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <EmptyState
          title="No Departments Found"
          description="There are currently no institutional departments registered on the platform."
        />
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col">
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Institutional Departments Directory</h3>
          <p className="text-xs text-slate-500">Super Admin overview of all registered multi-tenant departments.</p>
        </div>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">
          {departments.length} registered
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/75 text-slate-600 font-semibold uppercase tracking-wider">
              <th className="py-3 px-4 w-36">Code</th>
              <th className="py-3 px-4">Department Name</th>
              <th className="py-3 px-4">Description</th>
              <th className="py-3 px-4 w-24">Status</th>
              <th className="py-3 px-4 w-44">Created At</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {departments.map((dept) => (
              <tr key={dept.id} className="hover:bg-slate-50/60 transition-colors">
                <td className="py-3 px-4 font-mono font-bold text-indigo-700">
                  <span className="flex items-center gap-1.5">
                    <Hash className="h-3.5 w-3.5 text-slate-400" />
                    {dept.code}
                  </span>
                </td>
                <td className="py-3 px-4">
                  <div className="flex items-center gap-2">
                    <Building className="h-4 w-4 text-slate-400 shrink-0" />
                    <span className="font-semibold text-slate-900">{dept.name}</span>
                  </div>
                </td>
                <td className="py-3 px-4 text-slate-600 max-w-md truncate" title={dept.description || ''}>
                  {dept.description || <span className="text-slate-400 italic">No description provided</span>}
                </td>
                <td className="py-3 px-4">
                  <Badge variant={dept.is_active ? 'success' : 'danger'} size="sm">
                    {dept.is_active ? 'Active' : 'Inactive'}
                  </Badge>
                </td>
                <td className="py-3 px-4 font-mono text-slate-500 text-[11px] whitespace-nowrap">
                  {dept.created_at ? (
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3 w-3 text-slate-400" />
                      {new Date(dept.created_at).toISOString().substring(0, 10)}
                    </span>
                  ) : (
                    'N/A'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
