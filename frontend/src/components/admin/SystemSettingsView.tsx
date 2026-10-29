import React, { useState } from 'react';
import {
  Server,
  Shield,
  ShieldAlert,
  AlertTriangle,
  Save,
  CheckCircle2,
  HardDrive,
  Cpu,
  Lock,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import type { SystemSettings, SystemSettingsUpdate } from '../../types/admin';

export interface SystemSettingsViewProps {
  settings: SystemSettings;
  isUpdating: boolean;
  onUpdateSettings: (update: SystemSettingsUpdate) => Promise<void>;
}

export const SystemSettingsView: React.FC<SystemSettingsViewProps> = ({
  settings,
  isUpdating,
  onUpdateSettings,
}) => {
  const [maintenanceMode, setMaintenanceMode] = useState(settings.maintenance_mode);
  const [announcement, setAnnouncement] = useState(settings.system_announcement || '');
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatusMessage(null);
    await onUpdateSettings({
      maintenance_mode: maintenanceMode,
      system_announcement: announcement.trim() || null,
    });
    setStatusMessage('System operational settings updated and logged to audit chain.');
  };

  return (
    <div className="space-y-6">
      {statusMessage && (
        <Alert variant="success" title="Settings Saved">
          {statusMessage}
        </Alert>
      )}

      {/* Operational State Controls Form */}
      <form onSubmit={handleSubmit} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-5">
        <div className="flex items-center justify-between pb-4 border-b border-slate-100">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Institutional Operational Controls</h3>
            <p className="text-xs text-slate-500">Live operational switches for maintenance window and emergency banners.</p>
          </div>
          <Button
            type="submit"
            size="sm"
            isLoading={isUpdating}
            className="flex items-center gap-1.5 bg-indigo-600 text-white text-xs"
          >
            <Save className="h-4 w-4" />
            <span>Apply Operational Changes</span>
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
          <div className="p-4 rounded-lg border border-slate-200 bg-slate-50/50 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-semibold text-slate-800 block">Maintenance Mode</span>
                <span className="text-[11px] text-slate-500">
                  Restricts non-administrative access during institutional service windows.
                </span>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={maintenanceMode}
                  onChange={(e) => setMaintenanceMode(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-slate-300 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-amber-600"></div>
              </label>
            </div>
            {maintenanceMode && (
              <div className="flex items-center gap-2 p-2 rounded bg-amber-50 border border-amber-200 text-amber-800 text-[11px]">
                <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
                <span>Maintenance mode is active. Only authorized administrators may proceed.</span>
              </div>
            )}
          </div>

          <div className="p-4 rounded-lg border border-slate-200 bg-slate-50/50 space-y-2">
            <label htmlFor="sys-announcement" className="font-semibold text-slate-800 block">
              System Announcement Banner
            </label>
            <textarea
              id="sys-announcement"
              rows={2}
              placeholder="e.g. Scheduled maintenance on Sunday 02:00 UTC."
              value={announcement}
              onChange={(e) => setAnnouncement(e.target.value)}
              className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <span className="text-[11px] text-slate-400">Broadcasted across institutional dashboards.</span>
          </div>
        </div>
      </form>

      {/* Immutable / Environment Configuration Readout */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-6">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Platform Configuration & Security Attributes</h3>
          <p className="text-xs text-slate-500">
            Read-only configuration verified at service bootstrap. Secrets, DSN passwords, and tokens are scrubbed.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 text-xs">
          <div className="p-3.5 rounded-lg border border-slate-200 space-y-1">
            <div className="flex items-center gap-2 text-slate-500">
              <Server className="h-4 w-4 text-slate-400" />
              <span>Environment</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-900 capitalize">{settings.environment}</span>
              <Badge variant="default" size="sm">v{settings.app_version}</Badge>
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-slate-200 space-y-1">
            <div className="flex items-center gap-2 text-slate-500">
              <Lock className="h-4 w-4 text-slate-400" />
              <span>Session Expiration Ceilings</span>
            </div>
            <div className="text-slate-800 font-medium">
              Access: <span className="font-mono">{settings.auth_access_token_expire_minutes}m</span> | Refresh:{' '}
              <span className="font-mono">{settings.auth_refresh_token_expire_days}d</span>
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-slate-200 space-y-1">
            <div className="flex items-center gap-2 text-slate-500">
              <ShieldAlert className="h-4 w-4 text-slate-400" />
              <span>Biometric Matching</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Badge variant="danger" size="sm">
                Permanently Disabled
              </Badge>
              <span className="text-[10px] text-slate-400">(FR-BIO-001)</span>
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-slate-200 space-y-1">
            <div className="flex items-center gap-2 text-slate-500">
              <HardDrive className="h-4 w-4 text-slate-400" />
              <span>Object Storage & Bucket</span>
            </div>
            <div className="font-mono text-slate-800 text-[11px] truncate" title={settings.storage_bucket_name}>
              {settings.storage_bucket_name} ({settings.storage_region})
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-slate-200 space-y-1">
            <div className="flex items-center gap-2 text-slate-500">
              <Cpu className="h-4 w-4 text-slate-400" />
              <span>AI Analysis Engine</span>
            </div>
            <div className="font-semibold text-slate-800 capitalize">
              {settings.ai_provider}
            </div>
          </div>

          <div className="p-3.5 rounded-lg border border-slate-200 space-y-1">
            <div className="flex items-center gap-2 text-slate-500">
              <Shield className="h-4 w-4 text-slate-400" />
              <span>Database & Cache Status</span>
            </div>
            <div className="flex items-center gap-1.5 text-emerald-700 font-medium">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
              <span>Configured (DSN Masked)</span>
            </div>
          </div>
        </div>

        {/* CORS Origins */}
        <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2 text-xs">
          <span className="font-semibold text-slate-800 block">Allowlisted CORS Origins</span>
          <div className="flex flex-wrap gap-2">
            {settings.cors_allowed_origins.map((origin, idx) => (
              <span
                key={idx}
                className="font-mono text-[11px] px-2.5 py-1 rounded bg-white border border-slate-200 text-slate-700"
              >
                {origin}
              </span>
            ))}
          </div>
        </div>

        {/* Allowed Evidence MIME Types */}
        <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2 text-xs">
          <span className="font-semibold text-slate-800 block">Permitted Evidence Ingestion MIME Types</span>
          <div className="flex flex-wrap gap-1.5">
            {settings.allowed_evidence_mime_types.map((mime, idx) => (
              <span
                key={idx}
                className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-200/70 text-slate-700"
              >
                {mime}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
