import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as analyticsApi from '../api/analytics';
import { apiClient } from '../api/client';
import type {
  AnalyticsOverviewRead,
  IncidentAnalyticsRead,
  CaseAnalyticsRead,
  ReviewOutcomeAnalyticsRead,
  ReviewerWorkloadSummaryRead,
  ProcessingMetricsRead,
  IncidentDashboardRead,
  CaseDashboardRead,
  OperationsDashboardRead,
  SystemHealthDetailedRead,
} from '../types/analytics';

describe('Analytics API Client Functions', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('getAnalyticsOverview calls GET /analytics/overview with cleaned filter params', async () => {
    const mockOverview: AnalyticsOverviewRead = {
      total_incidents: 42,
      total_cases: 15,
      total_reviews: 120,
      active_investigations: 8,
      incidents_trend: [{ bucket_start: '2026-10-01T00:00:00Z', bucket_end: '2026-10-02T00:00:00Z', count: 5 }],
      cases_trend: [{ bucket_start: '2026-10-01T00:00:00Z', bucket_end: '2026-10-02T00:00:00Z', count: 2 }],
      time_range_start: '2026-10-01T00:00:00Z',
      time_range_end: '2026-10-28T00:00:00Z',
      department_id: 'dept-01',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockOverview);

    const result = await analyticsApi.getAnalyticsOverview({
      start_date: '2026-10-01T00:00:00Z',
      end_date: '2026-10-28T00:00:00Z',
      bucket: 'day',
      department_id: 'dept-01',
    });

    expect(spy).toHaveBeenCalledWith('/analytics/overview', {
      params: {
        start_date: '2026-10-01T00:00:00Z',
        end_date: '2026-10-28T00:00:00Z',
        bucket: 'day',
        department_id: 'dept-01',
      },
    });
    expect(result.total_incidents).toBe(42);
    expect(result.active_investigations).toBe(8);
  });

  it('getIncidentAnalytics calls GET /analytics/incidents', async () => {
    const mockIncidents: IncidentAnalyticsRead = {
      total_incidents: 100,
      incidents_by_category: { physical_altercation: 40, harassment: 30 },
      incidents_by_severity: { high: 20, medium: 50 },
      incidents_by_status: { reported: 10, assigned: 40 },
      incidents_by_department: { 'dept-01': 100 },
      time_series: [],
      avg_resolution_hours: 36.5,
      time_range_start: '2026-10-01T00:00:00Z',
      time_range_end: '2026-10-28T00:00:00Z',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockIncidents);
    const result = await analyticsApi.getIncidentAnalytics();

    expect(spy).toHaveBeenCalledWith('/analytics/incidents', { params: {} });
    expect(result.avg_resolution_hours).toBe(36.5);
  });

  it('getCaseAnalytics calls GET /analytics/cases', async () => {
    const mockCases: CaseAnalyticsRead = {
      total_cases: 25,
      cases_by_status: { under_investigation: 15, closed: 10 },
      cases_by_priority: { critical: 5, high: 10 },
      cases_by_escalation: { standard: 20, supervisor_review: 5 },
      active_investigations_count: 15,
      closed_cases_count: 10,
      time_series: [],
      time_range_start: '2026-10-01T00:00:00Z',
      time_range_end: '2026-10-28T00:00:00Z',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockCases);
    const result = await analyticsApi.getCaseAnalytics();

    expect(spy).toHaveBeenCalledWith('/analytics/cases', { params: {} });
    expect(result.closed_cases_count).toBe(10);
  });

  it('getReviewOutcomeAnalytics calls GET /analytics/reviews', async () => {
    const mockReviews: ReviewOutcomeAnalyticsRead = {
      total_reviews: 80,
      reviews_by_status: { confirmed: 60, rejected: 15, inconclusive: 5 },
      acceptance_rate: 0.75,
      rejection_rate: 0.1875,
      false_positive_reasons: { false_positive_motion: 10, poor_lighting_occlusion: 5 },
      time_series: [],
      time_range_start: '2026-10-01T00:00:00Z',
      time_range_end: '2026-10-28T00:00:00Z',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockReviews);
    const result = await analyticsApi.getReviewOutcomeAnalytics();

    expect(spy).toHaveBeenCalledWith('/analytics/reviews', { params: {} });
    expect(result.acceptance_rate).toBe(0.75);
    expect(result.false_positive_reasons.false_positive_motion).toBe(10);
  });

  it('getReviewerWorkload calls GET /analytics/workload with optional department scope', async () => {
    const mockWorkload: ReviewerWorkloadSummaryRead = {
      reviewers: [
        {
          reviewer_id: 'inv-1',
          reviewer_name: 'Lead Investigator Smith',
          reviewer_email: 'smith@campus.edu',
          department_id: 'dept-1',
          active_cases_count: 4,
          assigned_incidents_count: 6,
          completed_case_reviews_count: 12,
          completed_ai_segment_reviews_count: 45,
          pending_ai_segment_reviews_count: 3,
        },
      ],
      total_reviewers: 1,
      unassigned_incidents_count: 2,
      unassigned_cases_count: 1,
      department_id: 'dept-1',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockWorkload);
    const result = await analyticsApi.getReviewerWorkload('dept-1');

    expect(spy).toHaveBeenCalledWith('/analytics/workload', { params: { department_id: 'dept-1' } });
    expect(result.total_reviewers).toBe(1);
    expect(result.reviewers[0].active_cases_count).toBe(4);
  });

  it('getProcessingMetrics calls GET /analytics/processing-metrics', async () => {
    const mockMetrics: ProcessingMetricsRead = {
      ai_jobs: {
        total_logical_jobs: 50,
        pending_count: 2,
        running_count: 1,
        completed_count: 45,
        failed_count: 2,
        cancelled_count: 0,
        retry_attempts_count: 3,
        completion_rate: 0.9,
        failure_rate: 0.04,
        avg_processing_duration_seconds: 14.5,
        p95_processing_duration_seconds: 22.0,
        avg_queue_wait_seconds: 3.2,
        stale_running_count: 0,
      },
      notifications: {
        total_logical_notifications: 120,
        total_delivery_attempts: 125,
        delivered_count: 120,
        failed_count: 5,
        pending_count: 0,
        retry_exhausted_count: 0,
        delivery_success_rate: 0.96,
      },
      observation_window_start: '2026-10-01T00:00:00Z',
      observation_window_end: '2026-10-28T00:00:00Z',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockMetrics);
    const result = await analyticsApi.getProcessingMetrics();

    expect(spy).toHaveBeenCalledWith('/analytics/processing-metrics', { params: {} });
    expect(result.ai_jobs.completion_rate).toBe(0.9);
  });

  it('getIncidentDashboard and getCaseDashboard call /dashboards endpoints', async () => {
    const mockIncDash: IncidentDashboardRead = {
      total_incidents: 12,
      incidents_by_status: { triage: 4 },
      incidents_by_severity: { medium: 8 },
      incidents_by_department: { 'dept-1': 12 },
      total_evidence_items: 28,
      time_range_start: '2026-10-01T00:00:00Z',
      time_range_end: '2026-10-28T00:00:00Z',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const mockCaseDash: CaseDashboardRead = {
      total_cases: 7,
      cases_by_status: { active: 5 },
      cases_by_priority: { high: 4 },
      cases_by_escalation: { standard: 7 },
      active_investigations_count: 5,
      legal_hold_cases_count: 2,
      time_range_start: '2026-10-01T00:00:00Z',
      time_range_end: '2026-10-28T00:00:00Z',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValueOnce(mockIncDash)
      .mockResolvedValueOnce(mockCaseDash);

    const incRes = await analyticsApi.getIncidentDashboard();
    const caseRes = await analyticsApi.getCaseDashboard();

    expect(spy).toHaveBeenNthCalledWith(1, '/dashboards/incidents', { params: {} });
    expect(spy).toHaveBeenNthCalledWith(2, '/dashboards/cases', { params: {} });
    expect(incRes.total_evidence_items).toBe(28);
    expect(caseRes.legal_hold_cases_count).toBe(2);
  });

  it('getOperationsDashboard calls GET /dashboards/operations', async () => {
    const mockOpsDash: OperationsDashboardRead = {
      ai_jobs_total: 50,
      ai_jobs_by_status: { completed: 48, failed: 2 },
      ai_jobs_by_task_type: { violence_classifier: 50 },
      notifications_total: 100,
      notifications_by_channel: { email: 90, in_app: 10 },
      notifications_by_status: { delivered: 100 },
      delivery_attempts_total: 105,
      delivery_failures_total: 5,
      time_range_start: '2026-10-01T00:00:00Z',
      time_range_end: '2026-10-28T00:00:00Z',
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockOpsDash);
    const result = await analyticsApi.getOperationsDashboard();

    expect(spy).toHaveBeenCalledWith('/dashboards/operations', { params: {} });
    expect(result.ai_jobs_total).toBe(50);
    expect(result.delivery_failures_total).toBe(5);
  });

  it('getDetailedSystemHealth calls GET /health/system', async () => {
    const mockHealth: SystemHealthDetailedRead = {
      liveness: { status: 'healthy', version: '1.0.0', environment: 'production', timestamp: '2026-10-28' },
      readiness: { ready: true, timestamp: '2026-10-28', dependencies: { database: 'ok' } },
      database_status: 'healthy',
      queue_monitoring: { ai_job_queue_depth: 0, notification_queue_depth: 0, retry_exhausted_count: 0 },
      workers_total: 4,
      workers_active: 4,
      workers_stale: 0,
      workers: [],
      active_alerts: [],
      generated_at: '2026-10-28T12:00:00Z',
    };

    const spy = vi.spyOn(apiClient, 'get').mockResolvedValueOnce(mockHealth);
    const result = await analyticsApi.getDetailedSystemHealth();

    expect(spy).toHaveBeenCalledWith('/health/system');
    expect(result.database_status).toBe('healthy');
    expect(result.workers_active).toBe(4);
  });
});
