import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  submitIncident,
  listIncidents,
  getReviewQueue,
  getReviewQueueWorkload,
  getIncident,
} from '../api/incident';
import { ApiError } from '../types/api';
import type { IncidentCreate, IncidentRead } from '../types/incident';

describe('incidentApi service', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('submits a valid incident report with POST /api/v1/incidents', async () => {
    const mockCreated: IncidentRead = {
      id: 'b1111111-1111-1111-1111-111111111111',
      reference_number: 'INC-2026-A1B2C3D4',
      title: 'Academic misconduct observed in examination hall',
      description: 'Student was observed using unauthorized notes during midterm examination.',
      category: 'academic_misconduct',
      severity: 'medium',
      status: 'submitted',
      location: 'Sciences Complex Hall 3B',
      occurred_at: '2026-10-14T02:00:00Z',
      reporter_id: 'c2222222-2222-2222-2222-222222222222',
      department_id: 'a0000000-0000-0000-0000-000000000001',
      assignment_status: 'unassigned',
      created_at: '2026-10-14T02:30:00Z',
      updated_at: '2026-10-14T02:30:00Z',
    };

    let capturedUrl = '';
    let capturedMethod = '';
    let capturedBody = '';

    globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      capturedUrl = url;
      capturedMethod = init?.method || 'GET';
      capturedBody = init?.body as string;
      return Promise.resolve(
        new Response(JSON.stringify(mockCreated), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        })
      );
    });

    const payload: IncidentCreate = {
      title: 'Academic misconduct observed in examination hall',
      description: 'Student was observed using unauthorized notes during midterm examination.',
      category: 'academic_misconduct',
      severity: 'medium',
      location: 'Sciences Complex Hall 3B',
      occurred_at: '2026-10-14T02:00:00Z',
    };

    const result = await submitIncident(payload);

    expect(result.id).toBe(mockCreated.id);
    expect(result.reference_number).toBe('INC-2026-A1B2C3D4');
    expect(capturedUrl).toContain('/incidents');
    expect(capturedMethod).toBe('POST');
    const parsedBody = JSON.parse(capturedBody);
    expect(parsedBody.title).toBe(payload.title);
    expect(parsedBody.category).toBe('academic_misconduct');
  });

  it('lists incidents with query parameters via GET /api/v1/incidents', async () => {
    let capturedUrl = '';

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      capturedUrl = url;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: [],
            pagination: {
              page: 1,
              page_size: 20,
              total_items: 0,
              total_pages: 0,
              has_next: false,
              has_prev: false,
            },
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }
        )
      );
    });

    const res = await listIncidents({
      page: 2,
      page_size: 10,
      status: 'submitted',
      category: 'safety_hazard',
      severity: 'high',
      search: 'fire',
    });

    expect(capturedUrl).toContain('/incidents?');
    expect(capturedUrl).toContain('page=2');
    expect(capturedUrl).toContain('page_size=10');
    expect(capturedUrl).toContain('status=submitted');
    expect(capturedUrl).toContain('category=safety_hazard');
    expect(capturedUrl).toContain('severity=high');
    expect(capturedUrl).toContain('search=fire');
    expect(res.items).toEqual([]);
    expect(res.pagination?.page).toBe(1);
  });

  it('retrieves review queue incidents via GET /api/v1/incidents/queue', async () => {
    let capturedUrl = '';

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      capturedUrl = url;
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: [],
            pagination: {
              page: 1,
              page_size: 20,
              total_items: 0,
              total_pages: 0,
              has_next: false,
              has_prev: false,
            },
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }
        )
      );
    });

    await getReviewQueue({
      assignment_status: 'unassigned',
      severity: 'critical',
    });

    expect(capturedUrl).toContain('/incidents/queue?');
    expect(capturedUrl).toContain('assignment_status=unassigned');
    expect(capturedUrl).toContain('severity=critical');
  });

  it('retrieves workload summary via GET /api/v1/incidents/queue/workload', async () => {
    const mockSummary = {
      pending: 4,
      assigned: 2,
      unassigned: 2,
      overdue: 1,
      completed: 10,
      total: 14,
    };

    globalThis.fetch = vi.fn().mockImplementation(() => {
      return Promise.resolve(
        new Response(JSON.stringify(mockSummary), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );
    });

    const summary = await getReviewQueueWorkload();
    expect(summary.pending).toBe(4);
    expect(summary.overdue).toBe(1);
    expect(summary.total).toBe(14);
  });

  it('retrieves single incident by ID via GET /api/v1/incidents/:id', async () => {
    const mockIncident: IncidentRead = {
      id: 'abc-123',
      reference_number: 'INC-2026-TEST',
      title: 'Lab hazard',
      description: 'Chemical spilled in chemistry lab.',
      category: 'safety_hazard',
      severity: 'high',
      status: 'submitted',
      location: 'Chemistry Lab 4',
      occurred_at: '2026-10-15T00:00:00Z',
      reporter_id: 'user-1',
      department_id: 'dept-1',
      created_at: '2026-10-15T01:00:00Z',
      updated_at: '2026-10-15T01:00:00Z',
    };

    globalThis.fetch = vi.fn().mockImplementation(() => {
      return Promise.resolve(
        new Response(JSON.stringify(mockIncident), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      );
    });

    const incident = await getIncident('abc-123');
    expect(incident.reference_number).toBe('INC-2026-TEST');
  });

  it('handles backend 422 error gracefully with ApiError', async () => {
    globalThis.fetch = vi.fn().mockImplementation(() => {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            error: {
              code: 'VALIDATION_ERROR',
              message: 'Incident occurred_at timestamp cannot be in the future.',
              details: [
                {
                  field: 'occurred_at',
                  message: 'Incident occurred_at timestamp cannot be in the future.',
                },
              ],
            },
          }),
          {
            status: 422,
            headers: { 'Content-Type': 'application/json' },
          }
        )
      );
    });

    await expect(
      submitIncident({
        title: 'Future incident',
        description: 'Test narrative exceeding ten characters.',
        category: 'safety_hazard',
        location: 'Main Quad',
        occurred_at: '2099-01-01T00:00:00Z',
      })
    ).rejects.toThrow(ApiError);
  });
});
