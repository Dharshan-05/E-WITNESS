import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { IncidentIntakeWizard } from '../components/incident/IncidentIntakeWizard';
import { AuthContext, type AuthContextValue } from '../auth/AuthContext';
import * as incidentApi from '../api/incident';
import type { IncidentRead } from '../types/incident';

describe('IncidentIntakeWizard Component', () => {
  const mockAuthContext: AuthContextValue = {
    status: 'authenticated',
    user: {
      id: 'usr-12345678-0000',
      email: 'student@campus.edu',
      full_name: 'Student Reporter',
      account_status: 'active',
      is_active: true,
      role: {
        id: 'role-student',
        code: 'ROLE_STUDENT',
        name: 'Student',
        description: 'Campus student',
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
      id: 'role-student',
      code: 'ROLE_STUDENT',
      name: 'Student',
      description: 'Campus student',
      requires_department_scope: true,
      is_system_role: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    roleCode: 'ROLE_STUDENT',
    department: {
      id: 'dept-0001',
      code: 'CAMPUS_LIFE',
      name: 'Campus Life',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    sessionId: 'session-token',
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    refreshSession: vi.fn(),
    hasRole: vi.fn().mockReturnValue(false),
  };

  const renderWithAuth = (ui: React.ReactElement) => {
    return render(
      <AuthContext.Provider value={mockAuthContext}>
        {ui}
      </AuthContext.Provider>
    );
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders Step 1 (Classification) initially with category options', () => {
    renderWithAuth(<IncidentIntakeWizard />);

    expect(screen.getByText('Select Incident Category & Severity')).toBeInTheDocument();
    expect(screen.getByText('Academic Misconduct')).toBeInTheDocument();
    expect(screen.getByText('Physical Assault')).toBeInTheDocument();
    expect(screen.getByText('Safety Hazard')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Continue to Details/i })).toBeInTheDocument();
  });

  it('requires a category selection before allowing progression to Step 2', async () => {
    const user = userEvent.setup();
    renderWithAuth(<IncidentIntakeWizard />);

    // Click continue without selecting category
    await user.click(screen.getByRole('button', { name: /Continue to Details/i }));

    expect(screen.getByText('Category Required')).toBeInTheDocument();
    expect(
      screen.getByText('Please select a primary incident classification category.')
    ).toBeInTheDocument();
  });

  it('navigates to Step 2 when category is selected, and allows backing up to Step 1', async () => {
    const user = userEvent.setup();
    renderWithAuth(<IncidentIntakeWizard />);

    // Select Academic Misconduct category
    const categoryButton = screen.getByText('Academic Misconduct').closest('button');
    expect(categoryButton).toBeTruthy();
    await user.click(categoryButton!);

    // Click continue
    await user.click(screen.getByRole('button', { name: /Continue to Details/i }));

    // Should now be on Step 2
    expect(screen.getByText('Incident Narrative & Context')).toBeInTheDocument();
    expect(screen.getByLabelText(/Incident Title/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Factual Narrative Statement/i)).toBeInTheDocument();

    // Click Back to Classification
    await user.click(screen.getByRole('button', { name: /Back to Classification/i }));
    expect(screen.getByText('Select Incident Category & Severity')).toBeInTheDocument();
  });

  it('validates Step 2 fields and rejects future occurrence timestamp', async () => {
    const user = userEvent.setup();
    renderWithAuth(<IncidentIntakeWizard />);

    // Select category and proceed to Step 2
    await user.click(screen.getByText('Safety Hazard').closest('button')!);
    await user.click(screen.getByRole('button', { name: /Continue to Details/i }));

    // Submit with empty inputs
    await user.click(screen.getByRole('button', { name: /Review & Disclosures/i }));

    expect(screen.getByText('Incident title is required.')).toBeInTheDocument();
    expect(screen.getByText('Incident narrative description is required.')).toBeInTheDocument();
    expect(screen.getByText('Physical occurrence location is required.')).toBeInTheDocument();
    expect(screen.getByText('Date and time of occurrence is required.')).toBeInTheDocument();

    // Fill invalid future date
    const titleInput = screen.getByLabelText(/Incident Title/i);
    const descInput = screen.getByLabelText(/Factual Narrative Statement/i);
    const locInput = screen.getByLabelText(/Physical Location/i);
    const dateInput = screen.getByLabelText(/Date & Time of Occurrence/i);

    await user.type(titleInput, 'Chemical spill in organic chem laboratory');
    await user.type(descInput, 'A beaker cracked and spilled volatile solvent across the fume bench.');
    await user.type(locInput, 'Chem Hall 401');
    await user.type(dateInput, '2099-01-01T12:00');

    await user.click(screen.getByRole('button', { name: /Review & Disclosures/i }));
    expect(
      screen.getByText('Incident occurrence timestamp cannot be in the future.')
    ).toBeInTheDocument();
  });

  it('proceeds to Step 3 (Review & Disclosures) and submits report with generated reference number in Step 4', async () => {
    const user = userEvent.setup();

    const mockResponse: IncidentRead = {
      id: 'inc-1234-uuid',
      reference_number: 'INC-2026-F4E3D2C1',
      title: 'Water leak observed in primary server rack',
      description: 'Chilled water pipe overhead developed a pinhole leak above row C.',
      category: 'safety_hazard',
      severity: 'high',
      status: 'submitted',
      location: 'Datacenter Sub-Basement Room 012',
      occurred_at: '2026-10-14T10:00:00Z',
      reporter_id: 'usr-12345678-0000',
      department_id: 'dept-0001',
      assignment_status: 'unassigned',
      created_at: '2026-10-14T10:30:00Z',
      updated_at: '2026-10-14T10:30:00Z',
    };

    const submitSpy = vi.spyOn(incidentApi, 'submitIncident').mockResolvedValue(mockResponse);

    renderWithAuth(<IncidentIntakeWizard />);

    // Step 1: Select Safety Hazard and High severity
    await user.click(screen.getByText('Safety Hazard').closest('button')!);
    await user.click(screen.getByRole('radio', { name: /High/i }));
    await user.click(screen.getByRole('button', { name: /Continue to Details/i }));

    // Step 2: Fill narrative
    await user.type(screen.getByLabelText(/Incident Title/i), 'Water leak observed in primary server rack');
    await user.type(
      screen.getByLabelText(/Factual Narrative Statement/i),
      'Chilled water pipe overhead developed a pinhole leak above row C.'
    );
    await user.type(screen.getByLabelText(/Physical Location/i), 'Datacenter Sub-Basement Room 012');
    await user.type(screen.getByLabelText(/Date & Time of Occurrence/i), '2026-10-14T10:00');

    await user.click(screen.getByRole('button', { name: /Review & Disclosures/i }));

    // Step 3: Check review screen
    expect(screen.getByText('Review Submission & Institutional Disclosures')).toBeInTheDocument();
    expect(screen.getByText('Water leak observed in primary server rack')).toBeInTheDocument();
    expect(screen.getByText('Anonymous Reporting Policy:')).toBeInTheDocument();

    // Confirm & Submit
    await user.click(screen.getByRole('button', { name: /Confirm & Submit Report/i }));

    await waitFor(() => {
      expect(submitSpy).toHaveBeenCalledTimes(1);
    });

    const calledPayload = submitSpy.mock.calls[0][0];
    expect(calledPayload.title).toBe('Water leak observed in primary server rack');
    expect(calledPayload.category).toBe('safety_hazard');
    expect(calledPayload.severity).toBe('high');
    expect(calledPayload.location).toBe('Datacenter Sub-Basement Room 012');

    // Step 4: Confirmation screen
    await waitFor(() => {
      expect(screen.getByText('Incident Report Submitted Successfully')).toBeInTheDocument();
      expect(screen.getByText('INC-2026-F4E3D2C1')).toBeInTheDocument();
    });

    // Reset button
    await user.click(screen.getByRole('button', { name: /Report Another Incident/i }));
    expect(screen.getByText('Select Incident Category & Severity')).toBeInTheDocument();
  });
});
