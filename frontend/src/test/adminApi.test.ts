import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AdminApiClient } from '../api/admin';
import type { ApiClient } from '../api/client';
import type { SystemSettings, DepartmentSettings, DepartmentListItem } from '../types/admin';

describe('AdminApiClient', () => {
  let mockClient: {
    request: ReturnType<typeof vi.fn>;
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
    patch: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };
  let api: AdminApiClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    };
    api = new AdminApiClient(mockClient as unknown as ApiClient);
  });

  it('getSystemSettings requests /admin/settings/system', async () => {
    const mockSettings: SystemSettings = {
      environment: 'testing',
      app_version: '0.1.0',
      log_level: 'INFO',
      cors_allowed_origins: ['https://campus.internal'],
      auth_access_token_expire_minutes: 15,
      auth_refresh_token_expire_days: 7,
      biometric_matching_enabled: false,
      maintenance_mode: false,
      database_status: 'configured_redacted',
      redis_status: 'configured_redacted',
      storage_endpoint_url_redacted: 'https://storage.internal',
      storage_bucket_name: 'test-bucket',
      storage_region: 'us-east-1',
      ai_provider: 'disabled',
      max_upload_size_bytes: 104857600,
      allowed_evidence_mime_types: ['image/jpeg', 'video/mp4'],
    };
    mockClient.get.mockResolvedValueOnce(mockSettings);

    const res = await api.getSystemSettings();
    expect(res.environment).toBe('testing');
    expect(res.biometric_matching_enabled).toBe(false);
    expect(mockClient.get).toHaveBeenCalledWith('/admin/settings/system');
  });

  it('updateSystemSettings patches /admin/settings/system', async () => {
    const update = { maintenance_mode: true, system_announcement: 'Maintenance Alert' };
    mockClient.patch.mockResolvedValueOnce({ maintenance_mode: true, system_announcement: 'Maintenance Alert' });

    await api.updateSystemSettings(update);
    expect(mockClient.patch).toHaveBeenCalledWith('/admin/settings/system', update);
  });

  it('getCurrentDepartmentSettings requests /admin/settings/department', async () => {
    const mockDept: DepartmentSettings = {
      department_id: 'dept-111',
      code: 'SAFETY',
      name: 'Campus Safety',
      is_active: true,
      retention_period_days: 365,
      max_active_cases_per_investigator: 10,
      require_two_party_case_closure: true,
    };
    mockClient.get.mockResolvedValueOnce(mockDept);

    const res = await api.getCurrentDepartmentSettings();
    expect(res.code).toBe('SAFETY');
    expect(mockClient.get).toHaveBeenCalledWith('/admin/settings/department');
  });

  it('updateDepartmentSettings patches /admin/settings/department/:id', async () => {
    const deptId = 'dept-222';
    const update = { contact_email: 'new@safety.edu', retention_period_days: 180 };
    mockClient.patch.mockResolvedValueOnce({ department_id: deptId, ...update });

    await api.updateDepartmentSettings(deptId, update);
    expect(mockClient.patch).toHaveBeenCalledWith(`/admin/settings/department/${deptId}`, update);
  });

  it('listDepartments requests /admin/departments', async () => {
    const mockList: DepartmentListItem[] = [
      { id: '1', code: 'POLICE', name: 'Campus Police', is_active: true },
      { id: '2', code: 'HEALTH', name: 'Student Health', is_active: true },
    ];
    mockClient.get.mockResolvedValueOnce(mockList);

    const res = await api.listDepartments();
    expect(res).toHaveLength(2);
    expect(mockClient.get).toHaveBeenCalledWith('/admin/departments');
  });
});
