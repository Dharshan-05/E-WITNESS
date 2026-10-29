import { ApiClient } from './client';
import type { PaginatedResponse } from '../types/api';
import type {
  AuditEventExportRequest,
  AuditEventExportResponse,
  AuditSearchFilterParams,
  AuditVerificationReport,
  SecurityAuditEvent,
} from '../types/audit';

export class AuditApiClient {
  constructor(private readonly client: ApiClient = new ApiClient()) {}

  /**
   * Search security audit events with department boundary enforcement and pagination.
   */
  public async searchEvents(
    params: AuditSearchFilterParams = {}
  ): Promise<PaginatedResponse<SecurityAuditEvent>> {
    return this.client.get<PaginatedResponse<SecurityAuditEvent>>('/audit/events', {
      params: {
        actor_id: params.actor_id,
        action: params.action,
        target_type: params.target_type,
        target_id: params.target_id,
        department_id: params.department_id,
        outcome: params.outcome,
        start_time: params.start_time,
        end_time: params.end_time,
        page: params.page ?? 1,
        page_size: params.page_size ?? 50,
      },
    });
  }

  /**
   * Fetch a single security audit event with sensitive values redacted.
   */
  public async getEventDetail(eventId: string): Promise<SecurityAuditEvent> {
    return this.client.get<SecurityAuditEvent>(`/audit/events/${eventId}`);
  }

  /**
   * Cryptographically verify sequential hash chain integrity across ledger records.
   */
  public async verifyChain(
    startSequence: number = 1,
    limit: number = 1000
  ): Promise<AuditVerificationReport> {
    return this.client.get<AuditVerificationReport>('/audit/verify', {
      params: {
        start_sequence: startSequence,
        limit,
      },
    });
  }

  /**
   * Export authorized security audit events in CSV or JSON format with formula injection protection.
   */
  public async exportEvents(
    request: AuditEventExportRequest
  ): Promise<AuditEventExportResponse> {
    return this.client.post<AuditEventExportResponse>('/audit/events/export', request);
  }
}

export const auditApi = new AuditApiClient();
