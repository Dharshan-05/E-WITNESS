import React, { useState, useEffect, useCallback } from 'react';
import { Building2, Server, FolderTree } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { Alert } from '../components/ui/Alert';
import { Skeleton } from '../components/ui/Skeleton';
import { SystemSettingsView } from '../components/admin/SystemSettingsView';
import { DepartmentSettingsView } from '../components/admin/DepartmentSettingsView';
import { DepartmentManagementTable } from '../components/admin/DepartmentManagementTable';
import { useAuth } from '../auth/useAuth';
import { adminApi } from '../api/admin';
import type {
  SystemSettings,
  SystemSettingsUpdate,
  DepartmentSettings,
  DepartmentSettingsUpdate,
  DepartmentListItem,
} from '../types/admin';

export type AdminTab = 'system' | 'department' | 'directory';

export const AdminPage: React.FC = () => {
  const { hasRole, department: userDept } = useAuth();
  const isSuperAdmin = hasRole(['ROLE_SUPER_ADMIN', 'super_admin']);
  const isDeptAdmin = hasRole(['ROLE_DEPT_ADMIN', 'department_admin']);

  const [activeTab, setActiveTab] = useState<AdminTab>(isSuperAdmin ? 'system' : 'department');
  const [systemSettings, setSystemSettings] = useState<SystemSettings | null>(null);
  const [deptSettings, setDeptSettings] = useState<DepartmentSettings | null>(null);
  const [departmentsList, setDepartmentsList] = useState<DepartmentListItem[]>([]);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (isSuperAdmin) {
        const [sys, depts] = await Promise.all([
          adminApi.getSystemSettings(),
          adminApi.listDepartments(),
        ]);
        setSystemSettings(sys);
        setDepartmentsList(depts);

        // Also fetch department settings for user's assigned dept if any, or first dept in directory
        if (userDept?.id) {
          const dept = await adminApi.getDepartmentSettings(userDept.id);
          setDeptSettings(dept);
        } else if (depts.length > 0) {
          const dept = await adminApi.getDepartmentSettings(depts[0].id);
          setDeptSettings(dept);
        }
      } else if (isDeptAdmin) {
        const dept = await adminApi.getCurrentDepartmentSettings();
        setDeptSettings(dept);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load administrative settings.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [isSuperAdmin, isDeptAdmin, userDept]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleUpdateSystemSettings = async (update: SystemSettingsUpdate) => {
    setIsUpdating(true);
    try {
      const updated = await adminApi.updateSystemSettings(update);
      setSystemSettings(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to update system settings.';
      setError(msg);
      throw err;
    } finally {
      setIsUpdating(false);
    }
  };

  const handleUpdateDeptSettings = async (update: DepartmentSettingsUpdate) => {
    if (!deptSettings) return;
    setIsUpdating(true);
    try {
      const updated = await adminApi.updateDepartmentSettings(
        deptSettings.department_id,
        update
      );
      setDeptSettings(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to update department settings.';
      setError(msg);
      throw err;
    } finally {
      setIsUpdating(false);
    }
  };

  if (!isSuperAdmin && !isDeptAdmin) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Institutional Administration"
          subtitle="Platform configuration and tenant settings."
        />
        <Alert variant="error" title="Access Denied">
          You lack administrative privileges to access institutional or department settings.
        </Alert>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Institutional Administration & Settings"
        subtitle="Platform configuration, institutional department governance, and operational parameters."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Administration' },
        ]}
      />

      {error && (
        <Alert variant="error" title="Administrative Notice">
          {error}
        </Alert>
      )}

      {/* Tabs navigation */}
      <div className="border-b border-slate-200">
        <nav className="flex space-x-6" aria-label="Administration Tabs">
          {isSuperAdmin && (
            <button
              type="button"
              onClick={() => setActiveTab('system')}
              className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-xs transition-colors ${
                activeTab === 'system'
                  ? 'border-indigo-600 text-indigo-600 font-semibold'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
              }`}
            >
              <Server className="h-4 w-4" />
              <span>System Configuration</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => setActiveTab('department')}
            className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-xs transition-colors ${
              activeTab === 'department'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            }`}
          >
            <Building2 className="h-4 w-4" />
            <span>Department Settings</span>
          </button>

          {isSuperAdmin && (
            <button
              type="button"
              onClick={() => setActiveTab('directory')}
              className={`flex items-center gap-2 py-3 px-1 border-b-2 font-medium text-xs transition-colors ${
                activeTab === 'directory'
                  ? 'border-indigo-600 text-indigo-600 font-semibold'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
              }`}
            >
              <FolderTree className="h-4 w-4" />
              <span>Departments Directory</span>
            </button>
          )}
        </nav>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : (
        <div>
          {activeTab === 'system' && isSuperAdmin && systemSettings && (
            <SystemSettingsView
              settings={systemSettings}
              isUpdating={isUpdating}
              onUpdateSettings={handleUpdateSystemSettings}
            />
          )}

          {activeTab === 'department' && deptSettings && (
            <DepartmentSettingsView
              settings={deptSettings}
              isUpdating={isUpdating}
              onUpdateSettings={handleUpdateDeptSettings}
            />
          )}

          {activeTab === 'directory' && isSuperAdmin && (
            <DepartmentManagementTable departments={departmentsList} />
          )}
        </div>
      )}
    </div>
  );
};
