import { ApiClient } from './client';
import type {
  DepartmentListItem,
  DepartmentSettings,
  DepartmentSettingsUpdate,
  SystemSettings,
  SystemSettingsUpdate,
} from '../types/admin';

export class AdminApiClient {
  constructor(private readonly client: ApiClient = new ApiClient()) {}

  /**
   * Retrieve platform system configuration (Super Admin only).
   */
  public async getSystemSettings(): Promise<SystemSettings> {
    return this.client.get<SystemSettings>('/admin/settings/system');
  }

  /**
   * Update operational system settings (Super Admin only).
   */
  public async updateSystemSettings(
    body: SystemSettingsUpdate
  ): Promise<SystemSettings> {
    return this.client.patch<SystemSettings>('/admin/settings/system', body);
  }

  /**
   * Retrieve settings for the caller's assigned department.
   */
  public async getCurrentDepartmentSettings(): Promise<DepartmentSettings> {
    return this.client.get<DepartmentSettings>('/admin/settings/department');
  }

  /**
   * Retrieve department settings by ID (Dept Admin for own dept, Super Admin for any).
   */
  public async getDepartmentSettings(
    departmentId: string
  ): Promise<DepartmentSettings> {
    return this.client.get<DepartmentSettings>(
      `/admin/settings/department/${departmentId}`
    );
  }

  /**
   * Update department operational parameters with audit logging.
   */
  public async updateDepartmentSettings(
    departmentId: string,
    body: DepartmentSettingsUpdate
  ): Promise<DepartmentSettings> {
    return this.client.patch<DepartmentSettings>(
      `/admin/settings/department/${departmentId}`,
      body
    );
  }

  /**
   * List all departments for administrative oversight (Super Admin only).
   */
  public async listDepartments(): Promise<DepartmentListItem[]> {
    return this.client.get<DepartmentListItem[]>('/admin/departments');
  }
}

export const adminApi = new AdminApiClient();
