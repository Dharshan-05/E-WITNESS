import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  LayoutDashboard,
  AlertTriangle,
  FolderLock,
  Cpu,
  Download,
  AlertCircle,
  FileCheck2,
  Clock,
  Shield,
  Activity,
  Layers,
} from 'lucide-react';
import { useAuth } from '../../auth';
import * as analyticsApi from '../../api/analytics';
import type {
  AnalyticsFilter,
  AnalyticsOverviewRead,
  CaseAnalyticsRead,
  CaseDashboardRead,
  IncidentAnalyticsRead,
  IncidentDashboardRead,
  OperationsDashboardRead,
  ProcessingMetricsRead,
  ReviewOutcomeAnalyticsRead,
  ReviewerWorkloadSummaryRead,
  SystemHealthDetailedRead,
  TimeBucket,
} from '../../types/analytics';
import { KPIStatCard } from './KPIStatCard';
import { TimeSeriesChart } from './TimeSeriesChart';
import { DistributionBarChart } from './DistributionBarChart';
import { WorkloadTable } from './WorkloadTable';
import { DateRangePicker } from './DateRangePicker';
import { AIReviewMetricsCard } from './AIReviewMetricsCard';
import { ReportExportModal } from './ReportExportModal';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

export type DashboardTab = 'overview' | 'incidents' | 'cases' | 'ai_operations';

export const AnalyticsDashboardView: React.FC = () => {
  const { user, role } = useAuth();
  const roleCode = role?.code || '';
  const isSuperAdmin = roleCode === 'ROLE_SUPER_ADMIN' || roleCode === 'super_admin';
  const isDeptAdmin = roleCode === 'ROLE_DEPT_ADMIN' || roleCode === 'department_admin';
  const hasWorkloadAccess = isSuperAdmin || isDeptAdmin;
  const hasOpsAccess = isSuperAdmin || isDeptAdmin;

  const [activeTab, setActiveTab] = useState<DashboardTab>('overview');

  // Filter state (Defaults to last 30 days)
  const defaultDates = useRef(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - 30);
    return {
      start: start.toISOString(),
      end: end.toISOString(),
    };
  }).current();

  const [startDate, setStartDate] = useState<string | null>(defaultDates.start);
  const [endDate, setEndDate] = useState<string | null>(defaultDates.end);
  const [bucket, setBucket] = useState<TimeBucket>('day');

  // Data states
  const [overview, setOverview] = useState<AnalyticsOverviewRead | null>(null);
  const [incidentAnalytics, setIncidentAnalytics] = useState<IncidentAnalyticsRead | null>(null);
  const [caseAnalytics, setCaseAnalytics] = useState<CaseAnalyticsRead | null>(null);
  const [reviewAnalytics, setReviewAnalytics] = useState<ReviewOutcomeAnalyticsRead | null>(null);
  const [workload, setWorkload] = useState<ReviewerWorkloadSummaryRead | null>(null);
  const [processingMetrics, setProcessingMetrics] = useState<ProcessingMetricsRead | null>(null);
  const [incidentDashboard, setIncidentDashboard] = useState<IncidentDashboardRead | null>(null);
  const [caseDashboard, setCaseDashboard] = useState<CaseDashboardRead | null>(null);
  const [opsDashboard, setOpsDashboard] = useState<OperationsDashboardRead | null>(null);
  const [systemHealth, setSystemHealth] = useState<SystemHealthDetailedRead | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null);
  const [isExportModalOpen, setIsExportModalOpen] = useState<boolean>(false);

  // Monotonic request ID counter to prevent stale request overwrites
  const requestCounterRef = useRef(0);

  const loadDashboardData = useCallback(async (isRefresh = false) => {
    const currentRequestId = ++requestCounterRef.current;
    if (isRefresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    const filter: AnalyticsFilter = {
      start_date: startDate,
      end_date: endDate,
      bucket,
      department_id: isSuperAdmin ? undefined : user?.department_id || undefined,
    };

    try {
      // Execute verified analytical and operational queries
      const promises: Promise<unknown>[] = [
        analyticsApi.getAnalyticsOverview(filter).catch(() => null),
        analyticsApi.getIncidentAnalytics(filter).catch(() => null),
        analyticsApi.getCaseAnalytics(filter).catch(() => null),
        analyticsApi.getReviewOutcomeAnalytics(filter).catch(() => null),
        analyticsApi.getIncidentDashboard(filter).catch(() => null),
        analyticsApi.getCaseDashboard(filter).catch(() => null),
      ];

      if (hasWorkloadAccess) {
        promises.push(
          analyticsApi.getReviewerWorkload(filter.department_id).catch(() => null)
        );
      } else {
        promises.push(Promise.resolve(null));
      }

      if (hasOpsAccess) {
        promises.push(analyticsApi.getProcessingMetrics(filter).catch(() => null));
        promises.push(analyticsApi.getOperationsDashboard(filter).catch(() => null));
        promises.push(analyticsApi.getDetailedSystemHealth().catch(() => null));
      } else {
        promises.push(Promise.resolve(null), Promise.resolve(null), Promise.resolve(null));
      }

      const [
        resOverview,
        resIncidents,
        resCases,
        resReviews,
        resIncDashboard,
        resCaseDashboard,
        resWorkload,
        resProcessing,
        resOpsDashboard,
        resSystemHealth,
      ] = await Promise.all(promises);

      // Guard against stale asynchronous requests
      if (currentRequestId !== requestCounterRef.current) return;

      setOverview(resOverview as AnalyticsOverviewRead | null);
      setIncidentAnalytics(resIncidents as IncidentAnalyticsRead | null);
      setCaseAnalytics(resCases as CaseAnalyticsRead | null);
      setReviewAnalytics(resReviews as ReviewOutcomeAnalyticsRead | null);
      setIncidentDashboard(resIncDashboard as IncidentDashboardRead | null);
      setCaseDashboard(resCaseDashboard as CaseDashboardRead | null);
      setWorkload(resWorkload as ReviewerWorkloadSummaryRead | null);
      setProcessingMetrics(resProcessing as ProcessingMetricsRead | null);
      setOpsDashboard(resOpsDashboard as OperationsDashboardRead | null);
      setSystemHealth(resSystemHealth as SystemHealthDetailedRead | null);

      setLastRefreshedAt(new Date().toLocaleTimeString());
    } catch (err) {
      if (currentRequestId === requestCounterRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to retrieve analytics.');
      }
    } finally {
      if (currentRequestId === requestCounterRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, [startDate, endDate, bucket, isSuperAdmin, user?.department_id, hasWorkloadAccess, hasOpsAccess]);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  const handleFilterChange = (params: { startDate: string | null; endDate: string | null; bucket?: TimeBucket }) => {
    setStartDate(params.startDate);
    setEndDate(params.endDate);
    if (params.bucket) {
      setBucket(params.bucket);
    }
  };

  const tabs = [
    { id: 'overview' as const, label: 'Overview', icon: LayoutDashboard },
    { id: 'incidents' as const, label: 'Incident Analytics', icon: AlertTriangle },
    { id: 'cases' as const, label: 'Case Management & Workload', icon: FolderLock },
    { id: 'ai_operations' as const, label: 'AI Review & Operations', icon: Cpu },
  ];

  return (
    <div className="space-y-6" role="main" aria-label="Institutional Analytics and Operational Dashboard">
      {/* Header & Global Controls */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900">
              Institutional Analytics & Operational Metrics
            </h1>
            <Badge variant="primary" size="sm" className="font-mono text-[10px]">
              {isSuperAdmin ? 'Global Scope' : 'Department Scope'}
            </Badge>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Authoritative incident trends, case lifecycle statistics, investigator capacity, and human AI oversight telemetry.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          {lastRefreshedAt && (
            <span className="text-[11px] font-mono text-slate-400 hidden sm:inline">
              Updated: {lastRefreshedAt}
            </span>
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsExportModalOpen(true)}
            leftIcon={<Download className="h-4 w-4 text-indigo-600" />}
          >
            Export Report
          </Button>
        </div>
      </div>

      {/* Date Range & Aggregation Controls */}
      <DateRangePicker
        startDate={startDate}
        endDate={endDate}
        bucket={bucket}
        onFilterChange={handleFilterChange}
        onRefresh={() => loadDashboardData(true)}
        isRefreshing={isRefreshing}
      />

      {/* Error Banner */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700 shadow-xs">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
          <Button variant="ghost" size="sm" onClick={() => loadDashboardData()} className="ml-auto text-rose-700">
            Retry
          </Button>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="border-b border-slate-200">
        <nav className="flex space-x-6 overflow-x-auto" aria-label="Dashboard views">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 py-3 px-1 border-b-2 text-xs sm:text-sm font-semibold transition-colors whitespace-nowrap focus:outline-none ${
                  isActive
                    ? 'border-indigo-600 text-indigo-600'
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
                }`}
                aria-current={isActive ? 'page' : undefined}
              >
                <Icon className={`h-4 w-4 ${isActive ? 'text-indigo-600' : 'text-slate-400'}`} aria-hidden="true" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* TAB 1: OVERVIEW */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KPIStatCard
              title="Total Incidents"
              value={overview?.total_incidents ?? incidentDashboard?.total_incidents ?? 0}
              sublabel="Reported in selected window"
              variant="default"
              icon={<AlertTriangle className="h-5 w-5" />}
              loading={isLoading}
              tooltip="Total verified incident records matching role and department scope."
            />

            <KPIStatCard
              title="Active Investigations"
              value={overview?.active_investigations ?? caseDashboard?.active_investigations_count ?? 0}
              sublabel="Cases actively under investigation"
              variant="primary"
              icon={<FolderLock className="h-5 w-5" />}
              loading={isLoading}
              tooltip="Cases in active or under_investigation status."
            />

            <KPIStatCard
              title="AI Reviews Completed"
              value={overview?.total_reviews ?? reviewAnalytics?.total_reviews ?? 0}
              sublabel="Human oversight determinations"
              variant="success"
              icon={<Shield className="h-5 w-5" />}
              loading={isLoading}
              tooltip="Total candidate AI segment determinations completed by reviewers."
            />

            <KPIStatCard
              title="Total Evidence Items"
              value={incidentDashboard?.total_evidence_items ?? 0}
              sublabel="Digital evidence assets in custody"
              variant="default"
              icon={<FileCheck2 className="h-5 w-5" />}
              loading={isLoading}
              tooltip="Total evidence files linked across scoped incidents."
            />
          </div>

          {/* Time Series Trends */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <TimeSeriesChart
              title="Incident Ingestion Trend"
              subtitle="Daily count of submitted incident reports."
              data={overview?.incidents_trend || []}
              valueLabel="Incidents"
              lineColor="#4f46e5"
              fillColor="#e0e7ff"
            />

            <TimeSeriesChart
              title="Investigation Case Inception Trend"
              subtitle="Formal investigation cases created across observation window."
              data={overview?.cases_trend || []}
              valueLabel="Cases"
              lineColor="#0284c7"
              fillColor="#e0f2fe"
            />
          </div>

          {/* Quick Operational Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <span className="text-xs font-semibold uppercase text-slate-500">Legal Holds Enforced</span>
              <div className="text-2xl font-bold font-mono text-slate-900 mt-2">
                {caseDashboard?.legal_hold_cases_count ?? 0}
              </div>
              <p className="text-xs text-slate-500 mt-1">Cases with active legal preservation holds.</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <span className="text-xs font-semibold uppercase text-slate-500">Unassigned Incident Queue</span>
              <div className="text-2xl font-bold font-mono text-amber-700 mt-2">
                {workload?.unassigned_incidents_count ?? 0}
              </div>
              <p className="text-xs text-slate-500 mt-1">Incidents awaiting triage or investigator assignment.</p>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <span className="text-xs font-semibold uppercase text-slate-500">Unassigned Cases</span>
              <div className="text-2xl font-bold font-mono text-indigo-700 mt-2">
                {workload?.unassigned_cases_count ?? 0}
              </div>
              <p className="text-xs text-slate-500 mt-1">Cases without a designated lead investigator.</p>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: INCIDENT ANALYTICS */}
      {activeTab === 'incidents' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <KPIStatCard
              title="Total Incident Reports"
              value={incidentAnalytics?.total_incidents ?? incidentDashboard?.total_incidents ?? 0}
              sublabel="In observation period"
              variant="default"
              icon={<AlertTriangle className="h-5 w-5" />}
              loading={isLoading}
            />

            <KPIStatCard
              title="Avg Resolution Turnaround"
              value={
                incidentAnalytics?.avg_resolution_hours != null
                  ? `${incidentAnalytics.avg_resolution_hours.toFixed(1)} hrs`
                  : 'N/A'
              }
              sublabel="From intake to investigation resolution"
              variant="primary"
              icon={<Clock className="h-5 w-5" />}
              loading={isLoading}
            />

            <KPIStatCard
              title="Evidence Items Ingested"
              value={incidentDashboard?.total_evidence_items ?? 0}
              sublabel="Cryptographically fingerprinted items"
              variant="success"
              icon={<FileCheck2 className="h-5 w-5" />}
              loading={isLoading}
            />
          </div>

          <TimeSeriesChart
            title="Incident Volume Over Time"
            subtitle="Time-series frequency of incident reports."
            data={incidentAnalytics?.time_series || []}
            valueLabel="Incidents"
            lineColor="#4f46e5"
            fillColor="#e0e7ff"
          />

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            <DistributionBarChart
              title="Incidents by Category"
              subtitle="Reporting breakdown across categorized infractions."
              data={incidentAnalytics?.incidents_by_category ?? {}}
              totalCount={incidentAnalytics?.total_incidents}
              colorMap={{
                physical_altercation: 'bg-rose-500',
                theft: 'bg-amber-500',
                harassment: 'bg-purple-500',
                vandalism: 'bg-indigo-500',
                trespassing: 'bg-sky-500',
              }}
            />

            <DistributionBarChart
              title="Incidents by Severity"
              subtitle="Triage severity classification levels."
              data={incidentAnalytics?.incidents_by_severity ?? incidentDashboard?.incidents_by_severity ?? {}}
              totalCount={incidentAnalytics?.total_incidents ?? incidentDashboard?.total_incidents}
              colorMap={{
                critical: 'bg-rose-600',
                high: 'bg-orange-500',
                medium: 'bg-amber-500',
                low: 'bg-emerald-500',
              }}
            />

            <DistributionBarChart
              title="Incidents by Triage Status"
              subtitle="Current operational queue status."
              data={incidentAnalytics?.incidents_by_status ?? incidentDashboard?.incidents_by_status ?? {}}
              totalCount={incidentAnalytics?.total_incidents ?? incidentDashboard?.total_incidents}
              colorMap={{
                reported: 'bg-sky-500',
                triage: 'bg-amber-500',
                assigned: 'bg-indigo-500',
                under_investigation: 'bg-purple-600',
                resolved: 'bg-emerald-500',
                closed: 'bg-slate-400',
              }}
            />
          </div>
        </div>
      )}

      {/* TAB 3: CASE MANAGEMENT & WORKLOAD */}
      {activeTab === 'cases' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KPIStatCard
              title="Total Cases"
              value={caseAnalytics?.total_cases ?? caseDashboard?.total_cases ?? 0}
              sublabel="Investigation dossiers in scope"
              variant="default"
              icon={<FolderLock className="h-5 w-5" />}
              loading={isLoading}
            />

            <KPIStatCard
              title="Active Investigations"
              value={caseAnalytics?.active_investigations_count ?? caseDashboard?.active_investigations_count ?? 0}
              sublabel="Casework currently underway"
              variant="primary"
              icon={<Layers className="h-5 w-5" />}
              loading={isLoading}
            />

            <KPIStatCard
              title="Closed Cases"
              value={caseAnalytics?.closed_cases_count ?? 0}
              sublabel="Adjudicated or resolved dossiers"
              variant="success"
              icon={<Shield className="h-5 w-5" />}
              loading={isLoading}
            />

            <KPIStatCard
              title="Legal Holds"
              value={caseDashboard?.legal_hold_cases_count ?? 0}
              sublabel="Active litigation preservation holds"
              variant="warning"
              icon={<AlertCircle className="h-5 w-5" />}
              loading={isLoading}
            />
          </div>

          <TimeSeriesChart
            title="Case Creation Rate"
            subtitle="Formal case dossiers opened over observation period."
            data={caseAnalytics?.time_series || []}
            valueLabel="Cases Opened"
            lineColor="#0284c7"
            fillColor="#e0f2fe"
          />

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <DistributionBarChart
              title="Cases by Lifecycle Status"
              subtitle="Operational status distribution."
              data={caseAnalytics?.cases_by_status ?? caseDashboard?.cases_by_status ?? {}}
              totalCount={caseAnalytics?.total_cases ?? caseDashboard?.total_cases}
              colorMap={{
                draft: 'bg-slate-400',
                active: 'bg-indigo-500',
                under_investigation: 'bg-purple-600',
                under_review: 'bg-amber-500',
                closed: 'bg-emerald-600',
                reopened: 'bg-rose-500',
              }}
            />

            <DistributionBarChart
              title="Cases by Priority"
              subtitle="Assigned priority levels."
              data={caseAnalytics?.cases_by_priority ?? caseDashboard?.cases_by_priority ?? {}}
              totalCount={caseAnalytics?.total_cases ?? caseDashboard?.total_cases}
              colorMap={{
                critical: 'bg-rose-600',
                high: 'bg-orange-500',
                medium: 'bg-amber-500',
                low: 'bg-emerald-500',
              }}
            />

            <DistributionBarChart
              title="Cases by Escalation Tier"
              subtitle="Escalated investigation tiers."
              data={caseAnalytics?.cases_by_escalation ?? caseDashboard?.cases_by_escalation ?? {}}
              totalCount={caseAnalytics?.total_cases ?? caseDashboard?.total_cases}
              colorMap={{
                standard: 'bg-slate-500',
                supervisor_review: 'bg-amber-500',
                executive_escalation: 'bg-rose-600',
              }}
            />
          </div>

          {/* Workload Table for Authorized Personnel */}
          {hasWorkloadAccess ? (
            <WorkloadTable data={workload} loading={isLoading} />
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 text-center">
              Individual investigator capacity and workload distributions are restricted to supervisory personnel.
            </div>
          )}
        </div>
      )}

      {/* TAB 4: AI REVIEW & OPERATIONS */}
      {activeTab === 'ai_operations' && (
        <div className="space-y-6">
          <AIReviewMetricsCard
            reviewData={reviewAnalytics}
            processingData={processingMetrics?.ai_jobs}
            loading={isLoading}
          />

          {/* Deep Operational System Telemetry (Admins) */}
          {hasOpsAccess && systemHealth && (
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                    <Activity className="h-4 w-4 text-emerald-600" aria-hidden="true" />
                    <span>Real-Time Operational System Diagnostics</span>
                  </h4>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Background worker heartbeat status and asynchronous queue backlogs.
                  </p>
                </div>
                <Badge variant={systemHealth.database_status === 'healthy' ? 'success' : 'default'} size="sm">
                  DB: {systemHealth.database_status}
                </Badge>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center text-xs">
                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">AI Job Queue Depth</span>
                  <div className="text-lg font-bold font-mono text-slate-900 mt-1">
                    {systemHealth.queue_monitoring.ai_job_queue_depth}
                  </div>
                </div>

                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">Active Workers</span>
                  <div className="text-lg font-bold font-mono text-emerald-600 mt-1">
                    {systemHealth.workers_active} / {systemHealth.workers_total}
                  </div>
                </div>

                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">Stale Workers</span>
                  <div className="text-lg font-bold font-mono text-amber-600 mt-1">
                    {systemHealth.workers_stale}
                  </div>
                </div>

                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">Active Alerts</span>
                  <div className="text-lg font-bold font-mono text-slate-900 mt-1">
                    {systemHealth.active_alerts.length}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Operational Notification & Delivery Dispatch Metrics */}
          {hasOpsAccess && opsDashboard && (
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3">
              <h4 className="text-sm font-bold text-slate-900">Notification & Alert Delivery Operations</h4>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center text-xs">
                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">Notifications Total</span>
                  <div className="text-lg font-bold font-mono text-slate-900 mt-1">
                    {opsDashboard.notifications_total}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">Delivery Attempts</span>
                  <div className="text-lg font-bold font-mono text-slate-900 mt-1">
                    {opsDashboard.delivery_attempts_total}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">Delivery Failures</span>
                  <div className="text-lg font-bold font-mono text-rose-600 mt-1">
                    {opsDashboard.delivery_failures_total}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                  <span className="text-[10px] font-semibold text-slate-500 uppercase">Active Channels</span>
                  <div className="text-lg font-bold font-mono text-slate-900 mt-1">
                    {Object.keys(opsDashboard.notifications_by_channel).length}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Report Export Dialog */}
      <ReportExportModal
        isOpen={isExportModalOpen}
        onClose={() => setIsExportModalOpen(false)}
        startDate={startDate}
        endDate={endDate}
        departmentId={isSuperAdmin ? undefined : user?.department_id || undefined}
      />
    </div>
  );
};
