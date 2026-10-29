import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AuditApiClient } from '../api/audit';
import type { ApiClient } from '../api/client';
import type { SecurityAuditEvent, AuditVerificationReport, AuditEventExportResponse } from '../types/audit';

describe('AuditApiClient', () => {
  let mockClient: {
    request: ReturnType<typeof vi.fn>;
    get: ReturnType<typeof vi.fn>;
    post: ReturnType<typeof vi.fn>;
    patch: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };
  let api: AuditApiClient;

  beforeEach(() => {
    mockClient = {
      request: vi.fn(),
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    };
    api = new AuditApiClient(mockClient as unknown as ApiClient);
  });

  it('searchEvents requests /audit/events with mapped query parameters', async () => {
    const mockResponse = {
      items: [
        {
          id: '11111111-1111-1111-1111-111111111111',
          sequence_number: 1,
          action: 'auth:login:success',
          target_type: 'user',
          target_id: 'usr-1',
          outcome: 'success',
          event_hash: 'hash-1',
          created_at: '2026-10-29T00:00:00Z',
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
    };
    mockClient.get.mockResolvedValueOnce(mockResponse);

    const res = await api.searchEvents({ action: 'auth:login:success', page: 1, page_size: 20 });
    expect(res).toEqual(mockResponse);
    expect(mockClient.get).toHaveBeenCalledWith('/audit/events', {
      params: expect.objectContaining({
        action: 'auth:login:success',
        page: 1,
        page_size: 20,
      }),
    });
  });

  it('getEventDetail calls /audit/events/:id', async () => {
    const eventId = '22222222-2222-2222-2222-222222222222';
    const mockEvent: SecurityAuditEvent = {
      id: eventId,
      sequence_number: 2,
      action: 'incident:submitted',
      target_type: 'incident',
      target_id: 'INC-01',
      outcome: 'success',
      event_hash: 'hash-2',
      created_at: '2026-10-29T00:00:00Z',
      details: { token: '***REDACTED***' },
    };
    mockClient.get.mockResolvedValueOnce(mockEvent);

    const res = await api.getEventDetail(eventId);
    expect(res).toEqual(mockEvent);
    expect(mockClient.get).toHaveBeenCalledWith(`/audit/events/${eventId}`);
  });

  it('verifyChain requests /audit/verify with sequence and limit', async () => {
    const mockReport: AuditVerificationReport = {
      status: 'verified',
      chain_valid: true,
      total_events_verified: 50,
      first_sequence_number: 1,
      last_sequence_number: 50,
      tampered_event_ids: [],
      tampered_sequence_numbers: [],
      errors: [],
      disclaimer: 'Disclaimer text',
      verified_at: '2026-10-29T00:00:00Z',
    };
    mockClient.get.mockResolvedValueOnce(mockReport);

    const res = await api.verifyChain(1, 500);
    expect(res.status).toBe('verified');
    expect(mockClient.get).toHaveBeenCalledWith('/audit/verify', {
      params: { start_sequence: 1, limit: 500 },
    });
  });

  it('exportEvents posts payload to /audit/events/export', async () => {
    const mockExportResponse: AuditEventExportResponse = {
      export_id: '33333333-3333-3333-3333-333333333333',
      exported_at: '2026-10-29T00:00:00Z',
      export_format: 'csv',
      total_records: 10,
      content: 'id,sequence_number,action\n1,1,auth:login:success',
      hash_digest: 'sha256_mock_digest',
    };
    mockClient.post.mockResolvedValueOnce(mockExportResponse);

    const res = await api.exportEvents({ export_format: 'csv', limit: 50 });
    expect(res.total_records).toBe(10);
    expect(mockClient.post).toHaveBeenCalledWith('/audit/events/export', {
      export_format: 'csv',
      limit: 50,
    });
  });
});
