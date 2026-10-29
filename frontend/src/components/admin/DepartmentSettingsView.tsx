import React, { useState } from 'react';
import { Building2, Save, Mail, Calendar, Users, CheckSquare } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import type { DepartmentSettings, DepartmentSettingsUpdate } from '../../types/admin';

export interface DepartmentSettingsViewProps {
  settings: DepartmentSettings;
  isUpdating: boolean;
  onUpdateSettings: (update: DepartmentSettingsUpdate) => Promise<void>;
}

export const DepartmentSettingsView: React.FC<DepartmentSettingsViewProps> = ({
  settings,
  isUpdating,
  onUpdateSettings,
}) => {
  const [description, setDescription] = useState(settings.description || '');
  const [contactEmail, setContactEmail] = useState(settings.contact_email || '');
  const [retentionDays, setRetentionDays] = useState(settings.retention_period_days);
  const [maxCases, setMaxCases] = useState(settings.max_active_cases_per_investigator);
  const [requireTwoParty, setRequireTwoParty] = useState(settings.require_two_party_case_closure);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatusMessage(null);
    setErrorMessage(null);

    if (retentionDays < 30 || retentionDays > 3650) {
      setErrorMessage('Retention period must be between 30 and 3,650 days.');
      return;
    }
    if (maxCases < 1 || maxCases > 50) {
      setErrorMessage('Investigator case ceiling must be between 1 and 50 cases.');
      return;
    }

    try {
      await onUpdateSettings({
        description: description.trim() || null,
        contact_email: contactEmail.trim() || null,
        retention_period_days: retentionDays,
        max_active_cases_per_investigator: maxCases,
        require_two_party_case_closure: requireTwoParty,
      });
      setStatusMessage('Department settings updated and committed to audit trail.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to update department settings.';
      setErrorMessage(msg);
    }
  };

  return (
    <div className="space-y-6">
      {statusMessage && (
        <Alert variant="success" title="Settings Saved">
          {statusMessage}
        </Alert>
      )}

      {errorMessage && (
        <Alert variant="error" title="Validation Error">
          {errorMessage}
        </Alert>
      )}

      <form onSubmit={handleSubmit} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-6">
        {/* Department Identification Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-700">
              <Building2 className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-slate-900">{settings.name}</h3>
                <span className="font-mono text-xs text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100">
                  {settings.code}
                </span>
                <Badge variant={settings.is_active ? 'success' : 'danger'} size="sm">
                  {settings.is_active ? 'Active' : 'Deactivated'}
                </Badge>
              </div>
              <p className="text-xs text-slate-500 font-mono">Department ID: {settings.department_id}</p>
            </div>
          </div>

          <Button
            type="submit"
            size="sm"
            isLoading={isUpdating}
            className="flex items-center gap-1.5 bg-indigo-600 text-white text-xs self-start sm:self-auto"
          >
            <Save className="h-4 w-4" />
            <span>Save Department Settings</span>
          </Button>
        </div>

        {/* Settings Form Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
          <div className="space-y-4">
            <div>
              <label htmlFor="dept-desc" className="block font-medium text-slate-700 mb-1">
                Department Description
              </label>
              <textarea
                id="dept-desc"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Institutional purpose and jurisdiction notes"
                className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label htmlFor="dept-email" className="block font-medium text-slate-700 mb-1">
                <span className="flex items-center gap-1.5">
                  <Mail className="h-3.5 w-3.5 text-slate-400" />
                  Administrative Contact Email
                </span>
              </label>
              <input
                id="dept-email"
                type="email"
                value={contactEmail}
                onChange={(e) => setContactEmail(e.target.value)}
                placeholder="e.g. admin@campus-safety.edu"
                className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label htmlFor="dept-retention" className="block font-medium text-slate-700 mb-1">
                <span className="flex items-center gap-1.5">
                  <Calendar className="h-3.5 w-3.5 text-slate-400" />
                  Evidence & Incident Retention Threshold (Days)
                </span>
              </label>
              <input
                id="dept-retention"
                type="number"
                min="30"
                max="3650"
                value={retentionDays}
                onChange={(e) => setRetentionDays(Number(e.target.value))}
                className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                Evidence with active legal hold is permanently exempted from automatic purge.
              </span>
            </div>

            <div>
              <label htmlFor="dept-max-cases" className="block font-medium text-slate-700 mb-1">
                <span className="flex items-center gap-1.5">
                  <Users className="h-3.5 w-3.5 text-slate-400" />
                  Investigator Maximum Active Cases Ceiling
                </span>
              </label>
              <input
                id="dept-max-cases"
                type="number"
                min="1"
                max="50"
                value={maxCases}
                onChange={(e) => setMaxCases(Number(e.target.value))}
                className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <span className="text-[11px] text-slate-400 mt-0.5 block">
                Workload protection ceiling per assigned investigator (1 to 50).
              </span>
            </div>

            <div className="pt-2">
              <label className="flex items-start gap-2.5 p-3 rounded-lg border border-slate-200 bg-slate-50 cursor-pointer hover:bg-slate-100/60 transition-colors">
                <input
                  type="checkbox"
                  checked={requireTwoParty}
                  onChange={(e) => setRequireTwoParty(e.target.checked)}
                  className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 mt-0.5"
                />
                <div className="space-y-0.5">
                  <span className="font-semibold text-slate-800 flex items-center gap-1.5">
                    <CheckSquare className="h-3.5 w-3.5 text-indigo-600" />
                    Enforce Independent Two-Party Case Closure
                  </span>
                  <span className="text-[11px] text-slate-500 block leading-relaxed">
                    Requires separate supervisory approval before an investigator may formally close an active dossier.
                  </span>
                </div>
              </label>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
};
