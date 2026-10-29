import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { StudentProfileCard } from '../components/student/StudentProfileCard';
import { StudentVideoRecorder } from '../components/video/StudentVideoRecorder';
import { EvidenceUploader } from '../components/evidence/EvidenceUploader';
import { AuthContext, type AuthContextValue } from '../auth/AuthContext';
import * as geolocationUtil from '../utils/geolocation';

describe('Student Page & Live Video Evidence Workflow', () => {
  const mockStudentAuth: AuthContextValue = {
    status: 'authenticated',
    user: {
      id: '9a7578f6-807b-4d02-9702-1a20bed04185',
      email: 'student@campus.edu',
      full_name: 'Alex Student',
      institutional_id: 'STU-2026-9901',
      account_status: 'active',
      is_active: true,
      department_id: 'dept-dean-01',
      role: {
        id: 'role-student-id',
        code: 'ROLE_STUDENT',
        name: 'Student',
        description: 'Enrolled Campus Student',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      },
      session_id: '05d0d47f-efbf-420b-9d11-b3c26278f68c',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    role: {
      id: 'role-student-id',
      code: 'ROLE_STUDENT',
      name: 'Student',
      description: 'Enrolled Campus Student',
      requires_department_scope: true,
      is_system_role: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    roleCode: 'ROLE_STUDENT',
    department: {
      id: 'dept-dean-01',
      code: 'DEAN',
      name: 'Dean of Students Office',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    sessionId: '05d0d47f-efbf-420b-9d11-b3c26278f68c',
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    refreshSession: vi.fn(),
    hasRole: vi.fn().mockImplementation((roles) => {
      const arr = Array.isArray(roles) ? roles : [roles];
      return arr.includes('ROLE_STUDENT') || arr.includes('student');
    }),
  };

  const renderWithAuth = (ui: React.ReactElement, auth: AuthContextValue = mockStudentAuth) => {
    return render(<AuthContext.Provider value={auth}>{ui}</AuthContext.Provider>);
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    mockStudentAuth.hasRole = vi.fn().mockImplementation((roles) => {
      const arr = Array.isArray(roles) ? roles : [roles];
      return arr.includes('ROLE_STUDENT') || arr.includes('student');
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders student profile card with login details, student ID, department, and session', () => {
    const handleReport = vi.fn();
    const handleView = vi.fn();

    renderWithAuth(
      <StudentProfileCard
        onReportIncident={handleReport}
        onViewMySubmissions={handleView}
      />
    );

    expect(screen.getByText('Alex Student')).toBeInTheDocument();
    expect(screen.getByText('STU-2026-9901')).toBeInTheDocument();
    expect(screen.getByText('student@campus.edu')).toBeInTheDocument();
    expect(screen.getByText(/Dean of Students Office \(DEAN\)/i)).toBeInTheDocument();
    expect(screen.getByText('Active & Verified')).toBeInTheDocument();
    expect(screen.getByText(/Student Custody Standard/i)).toBeInTheDocument();

    const reportBtn = screen.getByRole('button', { name: /Record Video Incident/i });
    fireEvent.click(reportBtn);
    expect(handleReport).toHaveBeenCalledTimes(1);
  });

  it('automatically fetches GPS location and displays timestamp in StudentVideoRecorder', async () => {
    vi.spyOn(geolocationUtil, 'fetchCurrentGeolocation').mockResolvedValue({
      latitude: 37.774929,
      longitude: -122.419416,
      accuracy: 8,
      altitude: null,
      formattedLocation: 'GPS: 37.77493° N, 122.41942° W (±8m)',
      timestamp: '2026-10-29T10:00:00.000Z',
    });

    const handleConfirm = vi.fn();

    renderWithAuth(
      <StudentVideoRecorder onVideoConfirmed={handleConfirm} autoFetchLocation={true} />
    );

    expect(screen.getByText(/Live Video Evidence Capture/i)).toBeInTheDocument();
    expect(screen.getByText(/Local Upload Prohibited/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/GPS: 37.77493° N, 122.41942° W/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/Hardware System Clock/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Enable Camera/i })).toBeInTheDocument();
  });

  it('disables local file upload for students and presents live video recording in EvidenceUploader', () => {
    renderWithAuth(
      <EvidenceUploader incidentId="test-incident-uuid" />
    );

    // Verify student policy notice is present
    expect(
      screen.getByText(/Student Custody Policy: Direct File Upload Prohibited/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/students cannot upload files from disk/i)
    ).toBeInTheDocument();

    // Verify file drop zone is NOT active for students
    expect(screen.queryByTestId('upload-drop-zone')).not.toBeInTheDocument();

    // Verify live video evidence capture recorder is displayed
    expect(screen.getByText(/Live Video Evidence Capture/i)).toBeInTheDocument();
  });

  it('blocks drop and manual file changes for student accounts in EvidenceUploader', async () => {
    renderWithAuth(
      <EvidenceUploader incidentId="test-incident-uuid" />
    );

    const input = screen.getByTestId('upload-file-input') as HTMLInputElement;
    expect(input.disabled).toBe(true);

    const testFile = new File(['evidence dummy'], 'external_evidence.mp4', {
      type: 'video/mp4',
    });

    fireEvent.change(input, { target: { files: [testFile] } });

    await waitFor(() => {
      expect(
        screen.getByText(/Local disk uploads are disabled for student accounts/i)
      ).toBeInTheDocument();
    });
  });
});
