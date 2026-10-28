import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { IncidentsPage } from '../pages/IncidentsPage';
import { AuthContext, type AuthContextValue } from '../auth/AuthContext';
import type { RoleCode } from '../types/auth';
import * as incidentApi from '../api/incident';
import type { ReviewQueueWorkloadSummary } from '../types/incident';

describe('IncidentsPage Component & Role Scoping', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const createMockAuthContext = (
    roleCode: RoleCode,
    isReviewer: boolean
  ): AuthContextValue => ({
    status: 'authenticated',
    user: {
      id: 'usr-test-1',
      email: `${roleCode.toLowerCase()}@campus.edu`,
      full_name: 'Test User',
      account_status: 'active',
      is_active: true,
      role: {
        id: `role-${roleCode.toLowerCase()}`,
        code: roleCode,
        name: roleCode,
        description: 'Test Role',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      session_id: 'session-token',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    role: {
      id: `role-${roleCode.toLowerCase()}`,
      code: roleCode,
      name: roleCode,
      description: 'Test Role',
      requires_department_scope: true,
      is_system_role: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    roleCode: roleCode,
    department: {
      id: 'dept-safety-01',
      code: 'SAFETY',
      name: 'Campus Safety',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    sessionId: 'session-token',
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    refreshSession: vi.fn(),
    hasRole: vi.fn().mockImplementation((roles) => {
      const arr = Array.isArray(roles) ? roles : [roles];
      return isReviewer && arr.some((r) => r.includes('INVESTIGATOR') || r.includes('ADMIN'));
    }),
  });

  const renderWithRouterAndAuth = (auth: AuthContextValue) => {
    return render(
      <MemoryRouter initialEntries={['/incidents']}>
        <AuthContext.Provider value={auth}>
          <IncidentsPage />
        </AuthContext.Provider>
      </MemoryRouter>
    );
  };

  it('renders reviewer workspace with queue tab and workload cards for authorized investigators', async () => {
    const mockSummary: ReviewQueueWorkloadSummary = {
      pending: 5,
      assigned: 3,
      unassigned: 2,
      overdue: 0,
      completed: 12,
      total: 17,
    };

    vi.spyOn(incidentApi, 'getReviewQueueWorkload').mockResolvedValue(mockSummary);
    vi.spyOn(incidentApi, 'getReviewQueue').mockResolvedValue({
      items: [],
      pagination: {
        page: 1,
        page_size: 15,
        total_items: 0,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      },
    });

    const auth = createMockAuthContext('ROLE_INVESTIGATOR', true);

    renderWithRouterAndAuth(auth);

    // Verify statutory notice
    expect(screen.getByText(/Mandatory Statutory & Evidence Custody Governance/i)).toBeInTheDocument();

    // Verify Reviewer Tabs inside navigation
    const nav = screen.getByRole('navigation', { name: /Incident Management Views/i });
    expect(within(nav).getByRole('button', { name: /Department Triage Queue/i })).toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: /Report Incident/i })).toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: /My Submissions/i })).toBeInTheDocument();

    // Verify Workload Counters
    await waitFor(() => {
      expect(screen.getByText('Pending Triage')).toBeInTheDocument();
      expect(screen.getByText('5')).toBeInTheDocument();
    });
  });

  it('renders student workspace defaulting to report incident and hiding triage queue', () => {
    const auth = createMockAuthContext('ROLE_STUDENT', false);

    renderWithRouterAndAuth(auth);

    // Should NOT have Department Triage Queue tab
    expect(screen.queryByRole('button', { name: /Department Triage Queue/i })).not.toBeInTheDocument();

    // Should have Report Incident and My Submissions in nav
    const nav = screen.getByRole('navigation', { name: /Incident Management Views/i });
    expect(within(nav).getByRole('button', { name: /Report Incident/i })).toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: /My Submissions/i })).toBeInTheDocument();

    // Default view is Incident Intake Wizard (Step 1)
    expect(screen.getByText('Select Incident Category & Severity')).toBeInTheDocument();
  });

  it('switches tabs cleanly between Report Incident and My Submissions for a student', async () => {
    const user = userEvent.setup();
    const auth = createMockAuthContext('ROLE_STUDENT', false);

    vi.spyOn(incidentApi, 'listIncidents').mockResolvedValue({
      items: [],
      pagination: {
        page: 1,
        page_size: 50,
        total_items: 0,
        total_pages: 0,
        has_next: false,
        has_prev: false,
      },
    });

    renderWithRouterAndAuth(auth);

    // Currently on Report Incident
    expect(screen.getByText('Select Incident Category & Severity')).toBeInTheDocument();

    // Click My Submissions tab in nav
    const nav = screen.getByRole('navigation', { name: /Incident Management Views/i });
    const mySubmissionsTab = within(nav).getByRole('button', { name: /My Submissions/i });
    await user.click(mySubmissionsTab);

    await waitFor(() => {
      expect(screen.getByText('Your Submitted Reports')).toBeInTheDocument();
      expect(screen.getByText('No Incidents Reported')).toBeInTheDocument();
    });
  });
});
