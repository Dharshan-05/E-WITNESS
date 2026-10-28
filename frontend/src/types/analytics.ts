/**
 * Analytics, Dashboards, Workload, and Operational Monitoring Types.
 * Matches backend schemas:
 * - `backend/app/schemas/dashboard.py` (Phase 95)
 * - `backend/app/schemas/analytics.py` (Phase 96)
 * - `backend/app/schemas/workload.py` (Phase 97)
 * - `backend/app/schemas/report.py` (Phase 98)
 * - `backend/app/schemas/monitoring.py` (Phase 99)
 */

export type TimeBucket = 'hour' | 'day' | 'week' | 'month';

export interface DashboardDateFilter {
  start_date?: string | null;
  end_date?: string | null;
  department_id?: string | null;
}

export interface AnalyticsFilter extends DashboardDateFilter {
  bucket?: TimeBucket;
}

export interface TimeSeriesBucket {
  bucket_start: string;
  bucket_end: string;
  count: number;
}

// ─── Phase 95: Operational Dashboards ────────────────────────────────────────

export interface IncidentDashboardRead {
  total_incidents: number;
  incidents_by_status: Record<string, number>;
  incidents_by_severity: Record<string, number>;
  incidents_by_department: Record<string, number>;
  total_evidence_items: number;
  time_range_start: string;
  time_range_end: string;
  department_id?: string | null;
  generated_at: string;
}

export interface CaseDashboardRead {
  total_cases: number;
  cases_by_status: Record<string, number>;
  cases_by_priority: Record<string, number>;
  cases_by_escalation: Record<string, number>;
  active_investigations_count: number;
  legal_hold_cases_count: number;
  time_range_start: string;
  time_range_end: string;
  department_id?: string | null;
  generated_at: string;
}

export interface OperationsDashboardRead {
  ai_jobs_total: number;
  ai_jobs_by_status: Record<string, number>;
  ai_jobs_by_task_type: Record<string, number>;
  notifications_total: number;
  notifications_by_channel: Record<string, number>;
  notifications_by_status: Record<string, number>;
  delivery_attempts_total: number;
  delivery_failures_total: number;
  time_range_start: string;
  time_range_end: string;
  department_id?: string | null;
  generated_at: string;
}

// ─── Phase 96: Authorized Analytics ──────────────────────────────────────────

export interface IncidentAnalyticsRead {
  total_incidents: number;
  incidents_by_category: Record<string, number>;
  incidents_by_severity: Record<string, number>;
  incidents_by_status: Record<string, number>;
  incidents_by_department: Record<string, number>;
  time_series: TimeSeriesBucket[];
  avg_resolution_hours?: number | null;
  time_range_start: string;
  time_range_end: string;
  department_id?: string | null;
  generated_at: string;
}

export interface CaseAnalyticsRead {
  total_cases: number;
  cases_by_status: Record<string, number>;
  cases_by_priority: Record<string, number>;
  cases_by_escalation: Record<string, number>;
  active_investigations_count: number;
  closed_cases_count: number;
  time_series: TimeSeriesBucket[];
  time_range_start: string;
  time_range_end: string;
  department_id?: string | null;
  generated_at: string;
}

export interface ReviewOutcomeAnalyticsRead {
  total_reviews: number;
  reviews_by_status: Record<string, number>;
  acceptance_rate: number;
  rejection_rate: number;
  false_positive_reasons: Record<string, number>;
  time_series: TimeSeriesBucket[];
  time_range_start: string;
  time_range_end: string;
  department_id?: string | null;
  generated_at: string;
}

export interface AnalyticsOverviewRead {
  total_incidents: number;
  total_cases: number;
  total_reviews: number;
  active_investigations: number;
  incidents_trend: TimeSeriesBucket[];
  cases_trend: TimeSeriesBucket[];
  time_range_start: string;
  time_range_end: string;
  department_id?: string | null;
  generated_at: string;
}

// ─── Phase 97: Workload & Processing Metrics ─────────────────────────────────

export interface ReviewerWorkloadItem {
  reviewer_id: string;
  reviewer_name: string;
  reviewer_email: string;
  department_id: string;
  active_cases_count: number;
  assigned_incidents_count: number;
  completed_case_reviews_count: number;
  completed_ai_segment_reviews_count: number;
  pending_ai_segment_reviews_count: number;
}

export interface ReviewerWorkloadSummaryRead {
  reviewers: ReviewerWorkloadItem[];
  total_reviewers: number;
  unassigned_incidents_count: number;
  unassigned_cases_count: number;
  department_id?: string | null;
  generated_at: string;
}

export interface AIJobProcessingMetricsRead {
  total_logical_jobs: number;
  pending_count: number;
  running_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  retry_attempts_count: number;
  completion_rate: number;
  failure_rate: number;
  avg_processing_duration_seconds?: number | null;
  p95_processing_duration_seconds?: number | null;
  avg_queue_wait_seconds?: number | null;
  stale_running_count: number;
}

export interface NotificationProcessingMetricsRead {
  total_logical_notifications: number;
  total_delivery_attempts: number;
  delivered_count: number;
  failed_count: number;
  pending_count: number;
  retry_exhausted_count: number;
  delivery_success_rate: number;
}

export interface ProcessingMetricsRead {
  ai_jobs: AIJobProcessingMetricsRead;
  notifications: NotificationProcessingMetricsRead;
  observation_window_start: string;
  observation_window_end: string;
  department_id?: string | null;
  generated_at: string;
}

// ─── Phase 98: Controlled Report Generation & Export ─────────────────────────

export type ReportType = 'incidents' | 'cases' | 'operational_summary' | 'human_reviews';
export type ReportFormat = 'csv' | 'pdf';

export interface ReportExportRequest {
  report_type: ReportType;
  export_format: ReportFormat;
  start_date?: string | null;
  end_date?: string | null;
  department_id?: string | null;
}

export interface ReportExportRead {
  id: string;
  report_type: ReportType;
  export_format: ReportFormat;
  filename: string;
  row_count: number;
  file_size_bytes: number;
  generated_at: string;
}

// ─── Phase 99: Deep Operational Health & Queue Telemetry ──────────────────────

export interface QueueMonitoringRead {
  ai_job_queue_depth: number;
  oldest_queued_job_age_seconds?: number | null;
  notification_queue_depth: number;
  retry_exhausted_count: number;
}

export interface WorkerHeartbeatRead {
  id: string;
  worker_id: string;
  hostname: string;
  task_types: string[];
  status: string;
  last_heartbeat_at: string;
  is_stale: boolean;
  current_job_id?: string | null;
  metrics: Record<string, unknown>;
  created_at: string;
}

export interface OperationalAlertRead {
  id: string;
  alert_type: string;
  severity: string;
  title: string;
  message: string;
  details: Record<string, unknown>;
  is_active: boolean;
  triggered_at: string;
  resolved_at?: string | null;
}

export interface SystemHealthDetailedRead {
  liveness: {
    status: string;
    version: string;
    environment: string;
    timestamp: string;
  };
  readiness: {
    ready: boolean;
    timestamp: string;
    dependencies: Record<string, string>;
  };
  database_status: string;
  queue_monitoring: QueueMonitoringRead;
  workers_total: number;
  workers_active: number;
  workers_stale: number;
  workers: WorkerHeartbeatRead[];
  active_alerts: OperationalAlertRead[];
  generated_at: string;
}
