import { apiClient } from './client';
import type {
  AnalyticsFilter,
  AnalyticsOverviewRead,
  CaseAnalyticsRead,
  CaseDashboardRead,
  DashboardDateFilter,
  IncidentAnalyticsRead,
  IncidentDashboardRead,
  OperationsDashboardRead,
  ProcessingMetricsRead,
  ReportExportRequest,
  ReviewOutcomeAnalyticsRead,
  ReviewerWorkloadSummaryRead,
  SystemHealthDetailedRead,
} from '../types/analytics';

function cleanFilterParams(filter?: Record<string, unknown>): Record<string, string | number | boolean | undefined | null> {
  if (!filter) return {};
  const cleaned: Record<string, string | number | boolean | undefined | null> = {};
  for (const [k, v] of Object.entries(filter)) {
    if (v !== undefined && v !== null && v !== '') {
      cleaned[k] = v as string | number | boolean;
    }
  }
  return cleaned;
}

// ─── Phase 95: Operational Dashboards ────────────────────────────────────────

/**
 * Get aggregated incident metrics within bounded date filter.
 * GET /dashboards/incidents
 */
export async function getIncidentDashboard(filter?: DashboardDateFilter): Promise<IncidentDashboardRead> {
  return apiClient.get<IncidentDashboardRead>('/dashboards/incidents', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

/**
 * Get aggregated case investigation metrics within bounded date filter.
 * GET /dashboards/cases
 */
export async function getCaseDashboard(filter?: DashboardDateFilter): Promise<CaseDashboardRead> {
  return apiClient.get<CaseDashboardRead>('/dashboards/cases', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

/**
 * Get system operations metrics for AI analysis and notification delivery.
 * GET /dashboards/operations
 */
export async function getOperationsDashboard(filter?: DashboardDateFilter): Promise<OperationsDashboardRead> {
  return apiClient.get<OperationsDashboardRead>('/dashboards/operations', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

// ─── Phase 96: Authorized Analytics ──────────────────────────────────────────

/**
 * Get unified cross-domain analytical summary overview.
 * GET /analytics/overview
 */
export async function getAnalyticsOverview(filter?: AnalyticsFilter): Promise<AnalyticsOverviewRead> {
  return apiClient.get<AnalyticsOverviewRead>('/analytics/overview', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

/**
 * Get incident analytics and time-series histograms.
 * GET /analytics/incidents
 */
export async function getIncidentAnalytics(filter?: AnalyticsFilter): Promise<IncidentAnalyticsRead> {
  return apiClient.get<IncidentAnalyticsRead>('/analytics/incidents', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

/**
 * Get case analytics and investigation status trends.
 * GET /analytics/cases
 */
export async function getCaseAnalytics(filter?: AnalyticsFilter): Promise<CaseAnalyticsRead> {
  return apiClient.get<CaseAnalyticsRead>('/analytics/cases', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

/**
 * Get human review outcome analytics and acceptance rates for AI candidates.
 * GET /analytics/reviews
 */
export async function getReviewOutcomeAnalytics(filter?: AnalyticsFilter): Promise<ReviewOutcomeAnalyticsRead> {
  return apiClient.get<ReviewOutcomeAnalyticsRead>('/analytics/reviews', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

// ─── Phase 97: Workload & Processing Metrics ─────────────────────────────────

/**
 * Get reviewer workload distributions and pending reviews.
 * GET /analytics/workload
 */
export async function getReviewerWorkload(departmentId?: string | null): Promise<ReviewerWorkloadSummaryRead> {
  const params: Record<string, string> = {};
  if (departmentId) {
    params.department_id = departmentId;
  }
  return apiClient.get<ReviewerWorkloadSummaryRead>('/analytics/workload', { params });
}

/**
 * Get background job metrics and notification queue performance.
 * GET /analytics/processing-metrics
 */
export async function getProcessingMetrics(filter?: AnalyticsFilter): Promise<ProcessingMetricsRead> {
  return apiClient.get<ProcessingMetricsRead>('/analytics/processing-metrics', {
    params: cleanFilterParams(filter as Record<string, unknown>),
  });
}

// ─── Phase 98: Controlled Report Export ───────────────────────────────────────

/**
 * Trigger on-demand CSV or PDF report generation.
 * POST /reports/export
 */
export async function exportReport(payload: ReportExportRequest): Promise<{ blob: Blob; filename: string }> {
  // Use direct fetch with apiClient token handling to download binary stream
  const baseUrl = apiClient.getBaseUrl();
  const url = `${baseUrl}/reports/export`;
  const token = (typeof window !== 'undefined' && (window as unknown as { __ew_token?: string }).__ew_token) || null;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let message = `Export failed with status ${response.status}`;
    try {
      const err = await response.json();
      if (err?.error?.message) message = err.error.message;
    } catch {
      // Keep default message
    }
    throw new Error(message);
  }

  const disposition = response.headers.get('Content-Disposition') || '';
  let filename = `${payload.report_type}_report.${payload.export_format}`;
  const match = disposition.match(/filename="?([^";]+)"?/i);
  if (match && match[1]) {
    filename = match[1];
  }

  const blob = await response.blob();
  return { blob, filename };
}

// ─── Phase 99: Deep Operational Health ───────────────────────────────────────

/**
 * Get deep health diagnostics, worker heartbeats, and queue telemetry.
 * GET /health/system
 */
export async function getDetailedSystemHealth(): Promise<SystemHealthDetailedRead> {
  return apiClient.get<SystemHealthDetailedRead>('/health/system');
}
