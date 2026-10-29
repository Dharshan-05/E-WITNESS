import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AnalyticsDashboardView } from '../components/analytics/AnalyticsDashboardView';
import * as analyticsApi from '../api/analytics';
import * as authModule from '../auth';
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

describe('AnalyticsDashboardView Component', () => {
  const mockOverview: AnalyticsOverviewRead = {
    total_incidents: 45,
    total_cases: 18,
    total_reviews: 95,
    active_investigations: 12,
    incidents_trend: [
      { bucket_start: '2026-10-01T00:00:00Z', bucket_end: '2026-10-02T00:00:00Z', count: 15 },
      { bucket_start: '2026-10-02T00:00:00Z', bucket_end: '2026-10-03T00:00:00Z', count: 30 },
    ],
    cases_trend: [
      { bucket_start: '2026-10-01T00:00:00Z', bucket_end: '2026-10-02T00:00:00Z', count: 6 },
      { bucket_start: '2026-10-02T00:00:00Z', bucket_end: '2026-10-03T00:00:00Z', count: 12 },
    ],
    time_range_start: '2026-10-01T00:00:00Z',
    time_range_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockIncidentAnalytics: IncidentAnalyticsRead = {
    total_incidents: 45,
    incidents_by_category: { physical_altercation: 25, theft: 20 },
    incidents_by_severity: { high: 15, medium: 30 },
    incidents_by_status: { reported: 10, assigned: 35 },
    incidents_by_department: { 'dept-1': 45 },
    time_series: [
      { bucket_start: '2026-10-01T00:00:00Z', bucket_end: '2026-10-02T00:00:00Z', count: 15 },
      { bucket_start: '2026-10-02T00:00:00Z', bucket_end: '2026-10-03T00:00:00Z', count: 30 },
    ],
    avg_resolution_hours: 48.0,
    time_range_start: '2026-10-01T00:00:00Z',
    time_range_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockCaseAnalytics: CaseAnalyticsRead = {
    total_cases: 18,
    cases_by_status: { under_investigation: 12, closed: 6 },
    cases_by_priority: { high: 8, medium: 10 },
    cases_by_escalation: { standard: 18 },
    active_investigations_count: 12,
    closed_cases_count: 6,
    time_series: [],
    time_range_start: '2026-10-01T00:00:00Z',
    time_range_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockReviewAnalytics: ReviewOutcomeAnalyticsRead = {
    total_reviews: 95,
    reviews_by_status: { confirmed: 70, rejected: 20, inconclusive: 5 },
    acceptance_rate: 0.7368,
    rejection_rate: 0.2105,
    false_positive_reasons: { false_positive_motion: 15, poor_lighting_occlusion: 5 },
    time_series: [],
    time_range_start: '2026-10-01T00:00:00Z',
    time_range_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockWorkload: ReviewerWorkloadSummaryRead = {
    reviewers: [
      {
        reviewer_id: 'inv-1',
        reviewer_name: 'Lead Investigator Smith',
        reviewer_email: 'smith@campus.edu',
        department_id: 'dept-1',
        active_cases_count: 5,
        assigned_incidents_count: 8,
        completed_case_reviews_count: 15,
        completed_ai_segment_reviews_count: 60,
        pending_ai_segment_reviews_count: 4,
      },
    ],
    total_reviewers: 1,
    unassigned_incidents_count: 3,
    unassigned_cases_count: 2,
    department_id: 'dept-1',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockProcessingMetrics: ProcessingMetricsRead = {
    ai_jobs: {
      total_logical_jobs: 110,
      pending_count: 4,
      running_count: 2,
      completed_count: 100,
      failed_count: 4,
      cancelled_count: 0,
      retry_attempts_count: 6,
      completion_rate: 0.909,
      failure_rate: 0.036,
      avg_processing_duration_seconds: 18.2,
      p95_processing_duration_seconds: 28.5,
      avg_queue_wait_seconds: 4.1,
      stale_running_count: 0,
    },
    notifications: {
      total_logical_notifications: 200,
      total_delivery_attempts: 205,
      delivered_count: 200,
      failed_count: 5,
      pending_count: 0,
      retry_exhausted_count: 0,
      delivery_success_rate: 0.975,
    },
    observation_window_start: '2026-10-01T00:00:00Z',
    observation_window_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockIncidentDashboard: IncidentDashboardRead = {
    total_incidents: 45,
    incidents_by_status: { assigned: 35 },
    incidents_by_severity: { medium: 30 },
    incidents_by_department: { 'dept-1': 45 },
    total_evidence_items: 88,
    time_range_start: '2026-10-01T00:00:00Z',
    time_range_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockCaseDashboard: CaseDashboardRead = {
    total_cases: 18,
    cases_by_status: { under_investigation: 12 },
    cases_by_priority: { high: 8 },
    cases_by_escalation: { standard: 18 },
    active_investigations_count: 12,
    legal_hold_cases_count: 3,
    time_range_start: '2026-10-01T00:00:00Z',
    time_range_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockOpsDashboard: OperationsDashboardRead = {
    ai_jobs_total: 110,
    ai_jobs_by_status: { completed: 100 },
    ai_jobs_by_task_type: { violence_classifier: 110 },
    notifications_total: 200,
    notifications_by_channel: { email: 180, system_inbox: 20 },
    notifications_by_status: { delivered: 200 },
    delivery_attempts_total: 205,
    delivery_failures_total: 5,
    time_range_start: '2026-10-01T00:00:00Z',
    time_range_end: '2026-10-28T00:00:00Z',
    generated_at: '2026-10-28T12:00:00Z',
  };

  const mockHealth: SystemHealthDetailedRead = {
    liveness: { status: 'healthy', version: '1.0.0', environment: 'development', timestamp: '2026-10-28' },
    readiness: { ready: true, timestamp: '2026-10-28', dependencies: { database: 'ok' } },
    database_status: 'healthy',
    queue_monitoring: {
      ai_job_queue_depth: 3,
      oldest_queued_job_age_seconds: 12.0,
      notification_queue_depth: 0,
      retry_exhausted_count: 0,
    },
    workers_total: 4,
    workers_active: 4,
    workers_stale: 0,
    workers: [],
    active_alerts: [],
    generated_at: '2026-10-28T12:00:00Z',
  };

  beforeEach(() => {
    vi.restoreAllMocks();

    vi.spyOn(authModule, 'useAuth').mockReturnValue({
      user: {
        id: 'u-admin',
        email: 'deptadmin@campus.edu',
        full_name: 'Department Administrator',
        account_status: 'active',
        is_active: true,
        department_id: 'dept-1',
        session_id: 'sess-1',
        role: {
          id: 'r-admin',
          code: 'ROLE_DEPT_ADMIN',
          name: 'Department Admin',
          description: 'Administrator',
          requires_department_scope: true,
          is_system_role: false,
          created_at: '2026-01-01',
          updated_at: '2026-01-01',
        },
        created_at: '2026-01-01',
        updated_at: '2026-01-01',
      },
      role: {
        id: 'r-admin',
        code: 'ROLE_DEPT_ADMIN',
        name: 'Department Admin',
        description: 'Administrator',
        requires_department_scope: true,
        is_system_role: false,
        created_at: '2026-01-01',
        updated_at: '2026-01-01',
      },
      roleCode: 'ROLE_DEPT_ADMIN',
      department: null,
      sessionId: 'sess-1',
      status: 'authenticated',
      error: null,
      login: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn(),
      hasRole: vi.fn().mockReturnValue(true),
    });

    vi.spyOn(analyticsApi, 'getAnalyticsOverview').mockResolvedValue(mockOverview);
    vi.spyOn(analyticsApi, 'getIncidentAnalytics').mockResolvedValue(mockIncidentAnalytics);
    vi.spyOn(analyticsApi, 'getCaseAnalytics').mockResolvedValue(mockCaseAnalytics);
    vi.spyOn(analyticsApi, 'getReviewOutcomeAnalytics').mockResolvedValue(mockReviewAnalytics);
    vi.spyOn(analyticsApi, 'getIncidentDashboard').mockResolvedValue(mockIncidentDashboard);
    vi.spyOn(analyticsApi, 'getCaseDashboard').mockResolvedValue(mockCaseDashboard);
    vi.spyOn(analyticsApi, 'getReviewerWorkload').mockResolvedValue(mockWorkload);
    vi.spyOn(analyticsApi, 'getProcessingMetrics').mockResolvedValue(mockProcessingMetrics);
    vi.spyOn(analyticsApi, 'getOperationsDashboard').mockResolvedValue(mockOpsDashboard);
    vi.spyOn(analyticsApi, 'getDetailedSystemHealth').mockResolvedValue(mockHealth);
  });

  it('renders dashboard header and overview KPI stats from API response', async () => {
    render(<AnalyticsDashboardView />);

    expect(screen.getByText(/Institutional Analytics & Operational Metrics/i)).toBeInTheDocument();
    expect(screen.getByText(/Department Scope/i)).toBeInTheDocument();

    await waitFor(() => {
      // 45 incidents
      expect(screen.getAllByText('45')[0]).toBeInTheDocument();
      // 12 active investigations
      expect(screen.getAllByText('12')[0]).toBeInTheDocument();
      // 95 AI reviews
      expect(screen.getAllByText('95')[0]).toBeInTheDocument();
      // 88 evidence items
      expect(screen.getAllByText('88')[0]).toBeInTheDocument();
    });

    // Check time-series charts on overview tab
    expect(screen.getByText(/Incident Ingestion Trend/i)).toBeInTheDocument();
    expect(screen.getByText(/Investigation Case Inception Trend/i)).toBeInTheDocument();
  });

  it('navigates to Incident Analytics tab and displays category distributions', async () => {
    render(<AnalyticsDashboardView />);

    await waitFor(() => {
      expect(screen.getAllByText('45')[0]).toBeInTheDocument();
    });

    // Click Incident Analytics tab
    const incidentsTab = screen.getByRole('button', { name: /Incident Analytics/i });
    fireEvent.click(incidentsTab);

    await waitFor(() => {
      expect(screen.getByText(/Avg Resolution Turnaround/i)).toBeInTheDocument();
      expect(screen.getByText(/48\.0 hrs/i)).toBeInTheDocument();
      expect(screen.getByText(/Physical Altercation/i)).toBeInTheDocument();
    });
  });

  it('navigates to Case Management & Workload tab and renders workload table for supervisory roles', async () => {
    render(<AnalyticsDashboardView />);

    await waitFor(() => {
      expect(screen.getAllByText('45')[0]).toBeInTheDocument();
    });

    // Click Case Management & Workload tab
    const casesTab = screen.getByRole('button', { name: /Case Management & Workload/i });
    fireEvent.click(casesTab);

    await waitFor(() => {
      expect(screen.getByText(/Reviewer & Investigator Workloads/i)).toBeInTheDocument();
      expect(screen.getByText('Lead Investigator Smith')).toBeInTheDocument();
      expect(screen.getByText('Heavy Caseload')).toBeInTheDocument();
    });
  });

  it('navigates to AI Review & Operations tab and displays statutory disclaimer and review metrics', async () => {
    render(<AnalyticsDashboardView />);

    await waitFor(() => {
      expect(screen.getAllByText('45')[0]).toBeInTheDocument();
    });

    // Click AI Review & Operations tab
    const aiTab = screen.getByRole('button', { name: /AI Review & Operations/i });
    fireEvent.click(aiTab);

    await waitFor(() => {
      // Statutory AI Advisory notice
      expect(screen.getByText(/Institutional AI Advisory & Decision-Oversight Protocol/i)).toBeInTheDocument();
      expect(screen.getByText(/AI candidate annotations are non-authoritative machine hypotheses/i)).toBeInTheDocument();
      // Acceptance rate (73.7%)
      expect(screen.getByText('73.7%')).toBeInTheDocument();
      // Rejection rate (21.1%)
      expect(screen.getByText('21.1%')).toBeInTheDocument();
    });
  });

  it('updates dates when preset button is clicked in DateRangePicker', async () => {
    render(<AnalyticsDashboardView />);

    await waitFor(() => {
      expect(screen.getAllByText('45')[0]).toBeInTheDocument();
    });

    // Click 7D preset
    const preset7D = screen.getByRole('button', { name: '7D' });
    fireEvent.click(preset7D);

    await waitFor(() => {
      expect(analyticsApi.getAnalyticsOverview).toHaveBeenCalledTimes(2);
    });
  });

  it('opens Report Export modal when Export Report button is clicked', async () => {
    render(<AnalyticsDashboardView />);

    const exportBtn = screen.getByRole('button', { name: /Export Report/i });
    fireEvent.click(exportBtn);

    expect(screen.getByRole('dialog', { name: /Export Operational Report/i })).toBeInTheDocument();
    expect(screen.getAllByText(/Sanitized CSV/i)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/Official PDF/i)[0]).toBeInTheDocument();
  });
});
