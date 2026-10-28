import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiClient, generateCorrelationId } from '../api/client';
import { ApiError } from '../types/api';

describe('ApiClient (Typed Backend Client)', () => {
  let client: ApiClient;
  const originalFetch = global.fetch;

  beforeEach(() => {
    client = new ApiClient('/test-api/v1');
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('initializes with normalized base URL', () => {
    const c1 = new ApiClient('http://localhost:8000/api/v1///');
    expect(c1.getBaseUrl()).toBe('http://localhost:8000/api/v1');
  });

  it('generates non-empty correlation IDs', () => {
    const id1 = generateCorrelationId();
    const id2 = generateCorrelationId();
    expect(id1).toBeTruthy();
    expect(id2).toBeTruthy();
    expect(id1).not.toBe(id2);
  });

  it('executes successful GET request and returns JSON payload', async () => {
    const mockData = { id: 'case-123', reference_number: 'CASE-2026-00001' };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => mockData,
    });

    const result = await client.get<typeof mockData>('/cases/case-123');
    expect(result).toEqual(mockData);

    const [calledUrl, calledInit] = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(calledUrl).toBe('/test-api/v1/cases/case-123');
    expect(calledInit.method).toBe('GET');
    expect(calledInit.headers.get('Accept')).toBe('application/json');
    expect(calledInit.headers.get('X-Request-ID')).toBeTruthy();
  });

  it('appends query parameters cleanly', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ items: [] }),
    });

    await client.get('/cases', {
      params: { department_id: 'dept-99', limit: 25, active: true, skipped: undefined },
    });

    const [calledUrl] = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(calledUrl).toBe('/test-api/v1/cases?department_id=dept-99&limit=25&active=true');
  });

  it('injects Bearer authorization token when specified', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ user_id: 'user-1' }),
    });

    await client.get('/auth/me', { token: 'jwt.sample.token' });

    const [, calledInit] = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(calledInit.headers.get('Authorization')).toBe('Bearer jwt.sample.token');
  });

  it('sends JSON serialized body on POST requests', async () => {
    const payload = { title: 'New Campus Incident', severity: 'high' };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ id: 'inc-1', ...payload }),
    });

    const result = await client.post('/incidents', payload);
    expect(result).toEqual({ id: 'inc-1', ...payload });

    const [, calledInit] = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(calledInit.method).toBe('POST');
    expect(calledInit.headers.get('Content-Type')).toBe('application/json');
    expect(calledInit.body).toBe(JSON.stringify(payload));
  });

  it('parses structured backend ErrorResponse envelope on 4xx/5xx failures', async () => {
    const errorEnvelope = {
      error: {
        code: 'CASE_NOT_FOUND',
        message: 'The requested investigation case does not exist or department mismatch.',
        request_id: 'req-err-404',
        details: [{ field: 'case_id', message: 'Not found in department', error_type: 'not_found' }],
      },
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => errorEnvelope,
    });

    try {
      await client.get('/cases/missing-id');
      expect.fail('Should have thrown ApiError');
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(404);
      expect(apiErr.code).toBe('CASE_NOT_FOUND');
      expect(apiErr.message).toBe('The requested investigation case does not exist or department mismatch.');
      expect(apiErr.requestId).toBe('req-err-404');
      expect(apiErr.details).toHaveLength(1);
    }
  });

  it('handles network failure and wraps in safe ApiError', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Connection refused at 127.0.0.1:8000'));

    try {
      await client.get('/health/ready');
      expect.fail('Should have thrown ApiError');
    } catch (err: unknown) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(0);
      expect(apiErr.code).toBe('NETWORK_ERROR');
      expect(apiErr.message).toContain('Connection refused');
    }
  });
});
