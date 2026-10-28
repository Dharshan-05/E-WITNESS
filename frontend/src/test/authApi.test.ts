import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as authApi from '../api/auth';
import { ApiError } from '../types/api';

describe('Authentication API Module (authApi)', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('posts credentials to /auth/login and receives token response', async () => {
    const mockTokenResponse = {
      access_token: 'jwt-access-token-123',
      refresh_token: 'opaque-refresh-token-456',
      token_type: 'bearer',
      expires_in: 1800,
    };

    let capturedUrl = '';
    let capturedBody = '';
    let capturedHeaders: Headers | undefined;

    global.fetch = vi.fn().mockImplementation(async (url: string, init: RequestInit) => {
      capturedUrl = url;
      capturedBody = init.body as string;
      capturedHeaders = new Headers(init.headers);
      return new Response(JSON.stringify(mockTokenResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const result = await authApi.login({
      email: 'investigator@university.edu',
      password: 'Secure#Password123',
    });

    expect(capturedUrl).toContain('/api/v1/auth/login');
    expect(JSON.parse(capturedBody)).toEqual({
      email: 'investigator@university.edu',
      password: 'Secure#Password123',
    });
    expect(capturedHeaders?.get('X-Request-ID')).toBeTruthy();
    expect(capturedHeaders?.get('Content-Type')).toBe('application/json');
    expect(result).toEqual(mockTokenResponse);
  });

  it('handles 401 INVALID_CREDENTIALS error response correctly', async () => {
    const mockErrorEnvelope = {
      error: {
        code: 'INVALID_CREDENTIALS',
        message: 'Invalid email or password.',
        request_id: 'req-test-123',
      },
    };

    global.fetch = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify(mockErrorEnvelope), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      })
    );

    await expect(
      authApi.login({
        email: 'unknown@university.edu',
        password: 'WrongPassword!',
      })
    ).rejects.toThrow(ApiError);

    try {
      await authApi.login({
        email: 'unknown@university.edu',
        password: 'WrongPassword!',
      });
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(401);
      expect(apiErr.code).toBe('INVALID_CREDENTIALS');
      expect(apiErr.message).toBe('Invalid email or password.');
      expect(apiErr.requestId).toBe('req-test-123');
    }
  });

  it('introspects current user profile via GET /auth/me with bearer authorization', async () => {
    const mockProfile = {
      user: {
        id: 'user-uuid-1',
        email: 'investigator@university.edu',
        full_name: 'Detective Connor',
        account_status: 'active',
        is_active: true,
        department_id: 'dept-uuid-1',
        role_id: 'role-uuid-1',
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      role: {
        id: 'role-uuid-1',
        code: 'ROLE_INVESTIGATOR',
        name: 'Investigator',
        description: 'Examines evidence',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      department: {
        id: 'dept-uuid-1',
        code: 'FORENSICS',
        name: 'Digital Forensics',
        is_active: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      session_id: 'session-uuid-1',
    };

    let authHeader = '';
    global.fetch = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      const headers = new Headers(init.headers);
      authHeader = headers.get('Authorization') || '';
      return new Response(JSON.stringify(mockProfile), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const profile = await authApi.getCurrentUser('test-bearer-token');

    expect(authHeader).toBe('Bearer test-bearer-token');
    expect(profile.user.email).toBe('investigator@university.edu');
    expect(profile.role.code).toBe('ROLE_INVESTIGATOR');
    expect(profile.department?.code).toBe('FORENSICS');
  });

  it('rotates refresh token via POST /auth/refresh', async () => {
    const mockTokenResponse = {
      access_token: 'new-jwt-access-token',
      refresh_token: 'rotated-refresh-token',
      token_type: 'bearer',
      expires_in: 1800,
    };

    let capturedBody = '';
    global.fetch = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return new Response(JSON.stringify(mockTokenResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    const result = await authApi.refreshSession('old-refresh-token');

    expect(JSON.parse(capturedBody)).toEqual({
      refresh_token: 'old-refresh-token',
    });
    expect(result.access_token).toBe('new-jwt-access-token');
    expect(result.refresh_token).toBe('rotated-refresh-token');
  });

  it('terminates session via POST /auth/logout', async () => {
    const mockLogoutResponse = {
      status: 'success',
      message: 'All active sessions for the principal have been revoked.',
    };

    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(mockLogoutResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    );

    const result = await authApi.logout();

    expect(result.status).toBe('success');
    expect(result.message).toContain('revoked');
  });

  it('handles network failure with structured NETWORK_ERROR ApiError', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Connection refused'));

    await expect(
      authApi.login({
        email: 'test@university.edu',
        password: 'password123',
      })
    ).rejects.toThrow(ApiError);

    try {
      await authApi.login({
        email: 'test@university.edu',
        password: 'password123',
      });
    } catch (err: unknown) {
      const apiErr = err as ApiError;
      expect(apiErr.code).toBe('NETWORK_ERROR');
      expect(apiErr.status).toBe(0);
      expect(apiErr.message).toContain('Connection refused');
    }
  });
});
