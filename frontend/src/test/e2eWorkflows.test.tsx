// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../auth/AuthProvider';
import { useAuth } from '../auth/useAuth';
import { LoginPage } from '../pages/LoginPage';
import { IncidentIntakeWizard } from '../components/incident/IncidentIntakeWizard';
import { CaseDossierView } from '../components/case/CaseDossierView';
import { AISegmentReviewModal } from '../components/video/AISegmentReviewModal';
import { AuditPage } from '../pages/AuditPage';
import * as authApi from '../api/auth';
import * as incidentApi from '../api/incident';
import * as caseApi from '../api/case';
import { auditApi } from '../api/audit';
import { authStorage } from '../auth/auth.storage';
import { AuthContext, type AuthContextValue } from '../auth/AuthContext';
import type {
  CaseRead,
  CaseNoteRead,
  CaseAISegmentRead,
} from '../types/case';
import type { IncidentRead } from '../types/incident';

vi.mock('../api/audit', () => ({
  auditApi: {
    searchEvents: vi.fn(),
    getEventDetail: vi.fn(),
    verifyChain: vi.fn(),
    exportEvents: vi.fn(),
  },
}));

describe('Phase 119 Full-Stack Frontend E2E Integration Workflows', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authStorage.clear();
  });

  it('E2E Workflow 1: User authenticates, views session state, and executes secure logout', async () => {
    vi.spyOn(authApi, 'login').mockResolvedValue({
      access_token: 'fake-jwt-access-token-scenario-1',
      refresh_token: 'fake-jwt-refresh-token-scenario-1',
      token_type: 'bearer',
      expires_in: 900,
    });

    vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue({
      user: {
        id: 'usr-119-01',
        email: 'investigator.e2e@ewitness.edu',
        full_name: 'Lead Investigator E2E',
        account_status: 'active',
        is_active: true,
        department_id: 'dept-sec-01',
        role_id: 'role-inv',
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      role: {
        id: 'role-inv',
        code: 'ROLE_INVESTIGATOR',
        name: 'Investigator',
        description: 'Case Investigator',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      session_id: 'sess-119-01',
    });

    vi.spyOn(authApi, 'logout').mockResolvedValue({ status: 'success', message: 'Logged out' });

    function DashboardStub() {
      const { user, role, logout } = useAuth();
      return (
        <div>
          <h1>Investigation Dashboard</h1>
          <p data-testid="user-info">{user?.email} - {role?.code}</p>
          <button onClick={() => logout()}>Sign Out</button>
        </div>
      );
    }

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<DashboardStub />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    const emailInput = screen.getByLabelText(/Institutional Email/i);
    const passwordInput = screen.getByLabelText(/Password Credential/i);
    const submitBtn = screen.getByRole('button', { name: /Sign In/i });

    fireEvent.change(emailInput, { target: { value: 'investigator.e2e@ewitness.edu' } });
    fireEvent.change(passwordInput, { target: { value: 'ValidPassword123!' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText('Investigation Dashboard')).toBeInTheDocument();
      expect(screen.getByTestId('user-info')).toHaveTextContent('investigator.e2e@ewitness.edu - ROLE_INVESTIGATOR');
    });

    expect(authStorage.getRefreshToken()).toBe('fake-jwt-refresh-token-scenario-1');

    // Execute logout
    const logoutBtn = screen.getByRole('button', { name: /Sign Out/i });
    fireEvent.click(logoutBtn);

    await waitFor(() => {
      expect(authStorage.getRefreshToken()).toBeNull();
    });
  });

  it('E2E Workflow 2: Incident Intake Wizard multi-step validation and submission', async () => {
    const user = userEvent.setup();

    const mockAuthContext: AuthContextValue = {
      status: 'authenticated',
      user: {
        id: 'usr-student-01',
        email: 'student@ewitness.edu',
        full_name: 'Campus Student',
        department_id: 'dept-0001',
        account_status: 'active',
        is_active: true,
        role: {
          id: 'role-student',
          code: 'ROLE_STUDENT',
          name: 'Student',
          description: 'Campus Student',
          requires_department_scope: true,
          is_system_role: true,
          created_at: '2026-10-14T10:00:00Z',
          updated_at: '2026-10-14T10:00:00Z',
        },
        session_id: 'session-student-01',
        created_at: '2026-10-14T10:00:00Z',
        updated_at: '2026-10-14T10:00:00Z',
      },
      role: {
        id: 'role-student',
        code: 'ROLE_STUDENT',
        name: 'Student',
        description: 'Campus Student',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-14T10:00:00Z',
        updated_at: '2026-10-14T10:00:00Z',
      },
      roleCode: 'ROLE_STUDENT',
      department: {
        id: 'dept-0001',
        name: 'Campus Safety',
        code: 'SEC',
        is_active: true,
        created_at: '2026-10-14T10:00:00Z',
        updated_at: '2026-10-14T10:00:00Z',
      },
      sessionId: 'sess-01',
      error: null,
      login: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn().mockResolvedValue(true),
      hasRole: vi.fn().mockReturnValue(false),
    };

    const createdIncident: IncidentRead = {
      id: 'inc-119-99',
      reference_number: 'INC-202610-0999',
      department_id: 'dept-0001',
      title: 'Water leak observed in primary server rack',
      description: 'Chilled water pipe overhead developed a pinhole leak above row C.',
      category: 'safety_hazard',
      severity: 'high',
      status: 'submitted',
      location: 'Datacenter Sub-Basement Room 012',
      occurred_at: '2026-10-14T10:00:00Z',
      reporter_id: 'usr-student-01',
      created_at: '2026-10-14T10:30:00Z',
      updated_at: '2026-10-14T10:30:00Z',
    };

    const submitSpy = vi.spyOn(incidentApi, 'submitIncident').mockResolvedValue(createdIncident);

    render(
      <AuthContext.Provider value={mockAuthContext}>
        <MemoryRouter>
          <IncidentIntakeWizard />
        </MemoryRouter>
      </AuthContext.Provider>
    );

    // Step 1: Select Safety Hazard and High severity
    await user.click(screen.getByText('Safety Hazard').closest('button')!);
    await user.click(screen.getByRole('radio', { name: /High/i }));
    await user.click(screen.getByRole('button', { name: /Continue to Details/i }));

    // Step 2: Fill details
    await user.type(screen.getByLabelText(/Incident Title/i), 'Water leak observed in primary server rack');
    await user.type(
      screen.getByLabelText(/Factual Narrative Statement/i),
      'Chilled water pipe overhead developed a pinhole leak above row C.'
    );
    await user.type(screen.getByLabelText(/Physical Location/i), 'Datacenter Sub-Basement Room 012');
    await user.type(screen.getByLabelText(/Date & Time of Occurrence/i), '2026-10-14T10:00');

    await user.click(screen.getByRole('button', { name: /Review & Disclosures/i }));

    // Step 3: Review & Submit
    expect(screen.getByText('Review Submission & Institutional Disclosures')).toBeInTheDocument();
    expect(screen.getByText('Water leak observed in primary server rack')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Confirm & Submit Report/i }));

    await waitFor(() => {
      expect(submitSpy).toHaveBeenCalledTimes(1);
    });

    const calledPayload = submitSpy.mock.calls[0][0];
    expect(calledPayload.title).toBe('Water leak observed in primary server rack');
    expect(calledPayload.category).toBe('safety_hazard');
    expect(calledPayload.severity).toBe('high');
  }, 15000);

  it('E2E Workflow 3: Case Dossier displays notes and adds append-only investigation note', async () => {
    const caseId = 'case-119-01';

    const mockCase: CaseRead = {
      id: caseId,
      reference_number: 'CASE-2026-00119',
      title: 'Investigation into Lab Damage',
      summary: 'Formal security inquiry into damaged hardware in room 204.',
      priority: 'high',
      status: 'under_investigation',
      lead_investigator_id: 'usr-inv-01',
      created_by_id: 'usr-admin-01',
      department_id: 'dept-sec-01',
      version_id: 1,
      is_legal_hold: false,
      legal_hold_reason: null,
      closed_at: null,
      created_at: '2026-10-28T10:00:00Z',
      updated_at: '2026-10-28T10:00:00Z',
      incidents_count: 1,
      evidence_count: 1,
      ai_segments_count: 0,
      department_name: 'Campus Police',
      lead_investigator_name: 'Detective Morris',
    };

    const mockNote: CaseNoteRead = {
      id: 'note-01',
      case_id: caseId,
      author_id: 'usr-inv-01',
      content: 'Initial site walkthrough conducted at 10:30.',
      visibility: 'internal',
      version_id: 1,
      is_archived: false,
      evidence_reference_ids: [],
      created_at: '2026-10-28T10:35:00Z',
      updated_at: '2026-10-28T10:35:00Z',
    };

    const mockNewNote: CaseNoteRead = {
      id: 'note-02',
      case_id: caseId,
      author_id: 'usr-inv-01',
      content: 'Interviewed keycard holder who accessed room 204.',
      visibility: 'internal',
      version_id: 1,
      is_archived: false,
      evidence_reference_ids: [],
      created_at: '2026-10-28T11:00:00Z',
      updated_at: '2026-10-28T11:00:00Z',
    };

    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue([]);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue([]);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue([mockNote]);
    vi.spyOn(caseApi, 'getCaseActivityTimeline').mockResolvedValue({
      items: [],
      total_count: 0,
      has_more: false,
    });
    vi.spyOn(caseApi, 'listCaseAISegments').mockResolvedValue([]);
    const noteSpy = vi.spyOn(caseApi, 'createCaseNote').mockResolvedValue(mockNewNote);

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00119')).toBeInTheDocument();
    });

    // Switch to Case Notes tab
    const notesTab = screen.getByRole('button', { name: /case notes/i });
    fireEvent.click(notesTab);

    expect(await screen.findByText('Initial site walkthrough conducted at 10:30.')).toBeInTheDocument();

    // Add note
    const noteInput = screen.getByPlaceholderText(/record investigative observations/i);
    fireEvent.change(noteInput, { target: { value: 'Interviewed keycard holder who accessed room 204.' } });

    const submitNoteBtn = screen.getByRole('button', { name: /record case note/i });
    fireEvent.click(submitNoteBtn);

    await waitFor(() => {
      expect(noteSpy).toHaveBeenCalledWith(
        caseId,
        expect.objectContaining({
          content: 'Interviewed keycard holder who accessed room 204.',
        })
      );
    });
  });

  it('E2E Workflow 4: Video Evidence Review enforces statutory AI disclaimer and human determination', async () => {
    const mockCandidateSegment: CaseAISegmentRead = {
      id: 'seg-119-01',
      case_id: 'case-119-01',
      segment_id: 's-1',
      linked_by_id: 'usr-inv-01',
      investigative_relevance: 'candidate_lead',
      created_at: '2026-10-28T11:30:00Z',
      job_id: 'job-119-01',
      evidence_id: 'ev-119-01',
      incident_id: 'inc-119-99',
      start_seconds: 14.0,
      end_seconds: 22.5,
      duration_seconds: 8.5,
      score: 0.89,
      raw_score: 0.89,
      calibrated_score: 0.85,
      label: 'forced_entry_tool',
      model_name: 'violence-classifier',
      model_version: '0.1.0',
      review_status: 'pending_review',
      decision_revision: 0,
      is_override: false,
      advisory_disclaimer: 'Advisory candidate detection only. Does not establish facts.',
    };

    const onSubmitMock = vi.fn().mockResolvedValue(undefined);
    const onCloseMock = vi.fn();

    render(
      <AISegmentReviewModal
        isOpen={true}
        segment={mockCandidateSegment}
        onClose={onCloseMock}
        onSubmitReview={onSubmitMock}
      />
    );

    // Mandatory advisory disclaimer present
    expect(screen.getByText(/Institutional AI Governance Notice/i)).toBeInTheDocument();

    // Select "Confirm"
    const confirmBtn = screen.getByRole('button', { name: /Confirm/i });
    fireEvent.click(confirmBtn);

    // Substantive rationale required (min 10 chars)
    const rationaleInput = screen.getByPlaceholderText(/Provide detailed factual justification/i);
    fireEvent.change(rationaleInput, { target: { value: 'Visual confirmation of tool in subject hands.' } });

    // Submit review
    const submitBtn = screen.getByRole('button', { name: /Submit Determination/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(onSubmitMock).toHaveBeenCalledWith(
        expect.objectContaining({
          review_status: 'confirmed',
          review_rationale: 'Visual confirmation of tool in subject hands.',
        }),
        undefined
      );
      expect(onCloseMock).toHaveBeenCalled();
    });
  });

  it('E2E Workflow 5: Audit Log inspection displays cryptographic chain verification', async () => {
    vi.mocked(auditApi.searchEvents).mockResolvedValue({
      items: [
        {
          id: 'aud-119-01',
          sequence_number: 101,
          action: 'case:ai_segment:reviewed',
          actor_id: 'usr-inv-01',
          actor_role: 'ROLE_INVESTIGATOR',
          target_type: 'case',
          target_id: 'CASE-2026-00119',
          outcome: 'success',
          event_hash: 'abc123hash4567890123456789abcdef0123456789abcdef0123456789abcdef0',
          previous_event_hash: '000000genesis000000000000000000000000000000000000000000000000000',
          created_at: '2026-10-28T12:00:00Z',
          details: { segment_id: 'seg-119-01', decision: 'confirmed' },
        },
      ],
      pagination: {
        page: 1,
        page_size: 50,
        total_items: 1,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });

    vi.mocked(auditApi.verifyChain).mockResolvedValue({
      status: 'verified',
      chain_valid: true,
      total_events_verified: 101,
      first_sequence_number: 1,
      last_sequence_number: 101,
      tampered_event_ids: [],
      tampered_sequence_numbers: [],
      errors: [],
      disclaimer: 'Cryptographic hash chaining detects historical alteration...',
      verified_at: '2026-10-29T01:15:00Z',
    });

    render(
      <MemoryRouter>
        <AuditPage />
      </MemoryRouter>
    );

    expect(await screen.findByText('case:ai_segment:reviewed')).toBeInTheDocument();
    expect(screen.getByText('CASE-2026-00119')).toBeInTheDocument();

    // Click "Verify Integrity"
    const verifyBtn = screen.getByRole('button', { name: /Verify Integrity/i });
    fireEvent.click(verifyBtn);

    await waitFor(() => {
      expect(auditApi.verifyChain).toHaveBeenCalled();
      expect(screen.getByText(/Chain Verified \(Valid\)/i)).toBeInTheDocument();
    });

    expect(screen.getAllByText('101').length).toBeGreaterThan(0);
    expect(screen.getByText(/Cryptographic hash chaining detects/i)).toBeInTheDocument();
  });
});
