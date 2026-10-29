import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AdminPage } from '../pages/AdminPage';
import { adminApi } from '../api/admin';
import * as useAuthModule from '../auth/useAuth';
import type { SystemSettings, DepartmentSettings, DepartmentListItem } from '../types/admin';

vi.mock('../api/admin', () => ({
  adminApi: {
    getSystemSettings: vi.fn(),
    updateSystemSettings: vi.fn(),
    getCurrentDepartmentSettings: vi.fn(),
    getDepartmentSettings: vi.fn(),
    updateDepartmentSettings: vi.fn(),
    listDepartments: vi.fn(),
  },
}));

describe('AdminPage Component', () => {
  const sampleSystemSettings: SystemSettings = {
    environment: 'production',
    app_version: '1.0.0',
    log_level: 'INFO',
    cors_allowed_origins: ['https://campus.institution.edu'],
    auth_access_token_expire_minutes: 15,
    auth_refresh_token_expire_days: 7,
    biometric_matching_enabled: false,
    maintenance_mode: false,
    system_announcement: 'All systems operational',
    database_status: 'configured_redacted',
    redis_status: 'configured_redacted',
    storage_endpoint_url_redacted: 'https://s3.institution.internal',
    storage_bucket_name: 'prod-evidence',
    storage_region: 'us-east-1',
    ai_provider: 'disabled',
    max_upload_size_bytes: 104857600,
    allowed_evidence_mime_types: ['image/jpeg', 'video/mp4'],
  };

  const sampleDeptSettings: DepartmentSettings = {
    department_id: 'dept-1111-1111',
    code: 'POLICE',
    name: 'Campus Police Department',
    description: 'Campus law enforcement division',
    is_active: true,
    contact_email: 'dispatch@police.edu',
    retention_period_days: 365,
    max_active_cases_per_investigator: 12,
    require_two_party_case_closure: true,
  };

  const sampleDeptList: DepartmentListItem[] = [
    {
      id: 'dept-1111-1111',
      code: 'POLICE',
      name: 'Campus Police Department',
      description: 'Campus law enforcement division',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(adminApi.getSystemSettings).mockResolvedValue(sampleSystemSettings);
    vi.mocked(adminApi.getDepartmentSettings).mockResolvedValue(sampleDeptSettings);
    vi.mocked(adminApi.getCurrentDepartmentSettings).mockResolvedValue(sampleDeptSettings);
    vi.mocked(adminApi.listDepartments).mockResolvedValue(sampleDeptList);
  });

  it('renders all tabs and system settings for Super Admin', async () => {
    vi.spyOn(useAuthModule, 'useAuth').mockReturnValue({
      hasRole: (roles: string[]) => roles.includes('ROLE_SUPER_ADMIN') || roles.includes('super_admin'),
      department: { id: 'dept-1111-1111', code: 'POLICE', name: 'Campus Police' },
      user: { id: 'admin-1', email: 'super@institution.edu', full_name: 'Super Admin' },
      status: 'authenticated',
      role: { code: 'ROLE_SUPER_ADMIN' },
    } as unknown as ReturnType<typeof useAuthModule.useAuth>);

    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Institutional Administration & Settings')).toBeInTheDocument();
    expect(screen.getByText('System Configuration')).toBeInTheDocument();
    expect(screen.getByText('Department Settings')).toBeInTheDocument();
    expect(screen.getByText('Departments Directory')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/Platform Configuration & Security Attributes/i)).toBeInTheDocument();
    });

    expect(screen.getByText('production')).toBeInTheDocument();
    expect(screen.getByText('Permanently Disabled')).toBeInTheDocument();
  });

  it('allows Super Admin to update system announcement', async () => {
    vi.spyOn(useAuthModule, 'useAuth').mockReturnValue({
      hasRole: (roles: string[]) => roles.includes('ROLE_SUPER_ADMIN') || roles.includes('super_admin'),
      department: { id: 'dept-1111-1111', code: 'POLICE', name: 'Campus Police' },
      user: { id: 'admin-1', email: 'super@institution.edu', full_name: 'Super Admin' },
      status: 'authenticated',
      role: { code: 'ROLE_SUPER_ADMIN' },
    } as unknown as ReturnType<typeof useAuthModule.useAuth>);

    vi.mocked(adminApi.updateSystemSettings).mockResolvedValueOnce({
      ...sampleSystemSettings,
      system_announcement: 'Emergency drill at noon',
    });

    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Institutional Operational Controls/i)).toBeInTheDocument();
    });

    const textarea = screen.getByLabelText(/System Announcement Banner/i);
    fireEvent.change(textarea, { target: { value: 'Emergency drill at noon' } });

    const submitBtn = screen.getByRole('button', { name: /Apply Operational Changes/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(adminApi.updateSystemSettings).toHaveBeenCalledWith({
        maintenance_mode: false,
        system_announcement: 'Emergency drill at noon',
      });
    });
  });

  it('renders Department Settings for Department Admin without system tab', async () => {
    vi.spyOn(useAuthModule, 'useAuth').mockReturnValue({
      hasRole: (roles: string[]) => roles.includes('ROLE_DEPT_ADMIN') || roles.includes('department_admin'),
      department: { id: 'dept-1111-1111', code: 'POLICE', name: 'Campus Police' },
      user: { id: 'dept-admin-1', email: 'dept@institution.edu', full_name: 'Dept Admin' },
      status: 'authenticated',
      role: { code: 'ROLE_DEPT_ADMIN' },
    } as unknown as ReturnType<typeof useAuthModule.useAuth>);

    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    );

    expect(screen.queryByText('System Configuration')).not.toBeInTheDocument();
    expect(screen.getByText('Department Settings')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Campus Police Department')).toBeInTheDocument();
    });

    expect(screen.getByDisplayValue('dispatch@police.edu')).toBeInTheDocument();
    expect(screen.getByDisplayValue('365')).toBeInTheDocument();
  });

  it('denies access to unauthorized user', () => {
    vi.spyOn(useAuthModule, 'useAuth').mockReturnValue({
      hasRole: () => false,
      department: null,
      user: { id: 'student-1', email: 'student@institution.edu', full_name: 'Student' },
      status: 'authenticated',
      role: { code: 'ROLE_STUDENT' },
    } as unknown as ReturnType<typeof useAuthModule.useAuth>);

    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/Access Denied/i)).toBeInTheDocument();
    expect(screen.getByText(/You lack administrative privileges/i)).toBeInTheDocument();
  });
});
