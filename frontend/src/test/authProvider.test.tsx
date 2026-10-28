import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import React from 'react';
import { AuthProvider } from '../auth/AuthProvider';
import { useAuth } from '../auth/useAuth';
import { authStorage } from '../auth/auth.storage';
import * as authApi from '../api/auth';
import type { CurrentUserResponse, TokenResponse } from '../types/auth';

const ConsumerComponent: React.FC = () => {
  const { status, user, role, roleCode, logout, hasRole } = useAuth();
  return (
    <div>
      <div data-testid="status">{status}</div>
      <div data-testid="email">{user?.email || 'no-email'}</div>
      <div data-testid="role">{role?.name || roleCode || 'no-role'}</div>
      <div data-testid="has-investigator">
        {hasRole('ROLE_INVESTIGATOR') ? 'is-investigator' : 'not-investigator'}
      </div>
      <button onClick={() => logout()}>Sign Out</button>
    </div>
  );
};

describe('AuthProvider & Session Lifecycle', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    authStorage.clear();
  });

  afterEach(() => {
    authStorage.clear();
  });

  it('initializes to unauthenticated when no stored refresh token exists', async () => {
    render(
      <AuthProvider>
        <ConsumerComponent />
      </AuthProvider>
    );

    // Initial check may show initializing or unauthenticated after microtask
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId('status').textContent).toBe('unauthenticated');
    expect(screen.getByTestId('email').textContent).toBe('no-email');
  });

  it('restores authenticated session on mount when valid refresh token is stored', async () => {
    authStorage.setRefreshToken('valid-stored-refresh-token');

    const mockTokens: TokenResponse = {
      access_token: 'new-access-token',
      refresh_token: 'new-refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
    };

    const mockProfile: CurrentUserResponse = {
      user: {
        id: 'u-1',
        email: 'restored@university.edu',
        full_name: 'Restored User',
        account_status: 'active',
        is_active: true,
        department_id: 'd-1',
        role_id: 'r-1',
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      role: {
        id: 'r-1',
        code: 'ROLE_INVESTIGATOR',
        name: 'Investigator',
        description: 'Case Investigator',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      department: {
        id: 'd-1',
        code: 'FORENSICS',
        name: 'Digital Forensics',
        is_active: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      session_id: 'sess-1',
    };

    vi.spyOn(authApi, 'refreshSession').mockResolvedValue(mockTokens);
    vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue(mockProfile);

    render(
      <AuthProvider>
        <ConsumerComponent />
      </AuthProvider>
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId('status').textContent).toBe('authenticated');
    expect(screen.getByTestId('email').textContent).toBe('restored@university.edu');
    expect(screen.getByTestId('role').textContent).toBe('Investigator');
    expect(screen.getByTestId('has-investigator').textContent).toBe('is-investigator');
    expect(authStorage.getRefreshToken()).toBe('new-refresh-token');
  });

  it('resets to unauthenticated and clears storage if stored refresh token fails', async () => {
    authStorage.setRefreshToken('expired-refresh-token');

    vi.spyOn(authApi, 'refreshSession').mockRejectedValue(new Error('Invalid token'));

    render(
      <AuthProvider>
        <ConsumerComponent />
      </AuthProvider>
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId('status').textContent).toBe('unauthenticated');
    expect(authStorage.getRefreshToken()).toBeNull();
  });

  it('performs login and updates context to authenticated', async () => {
    const mockTokens: TokenResponse = {
      access_token: 'login-access-token',
      refresh_token: 'login-refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
    };

    const mockProfile: CurrentUserResponse = {
      user: {
        id: 'u-2',
        email: 'logged.in@university.edu',
        full_name: 'Logged In User',
        account_status: 'active',
        is_active: true,
        department_id: null,
        role_id: 'r-2',
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      role: {
        id: 'r-2',
        code: 'ROLE_DEPT_ADMIN',
        name: 'Department Administrator',
        description: 'Admin',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      session_id: 'sess-2',
    };

    vi.spyOn(authApi, 'login').mockResolvedValue(mockTokens);
    vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue(mockProfile);

    let authContextLogin: ((creds: { email: string; password: string }) => Promise<void>) | null = null;

    const LoginConsumer: React.FC = () => {
      const { login, status, user } = useAuth();
      authContextLogin = login;
      return (
        <div>
          <div data-testid="status">{status}</div>
          <div data-testid="email">{user?.email || 'none'}</div>
        </div>
      );
    };

    render(
      <AuthProvider>
        <LoginConsumer />
      </AuthProvider>
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId('status').textContent).toBe('unauthenticated');

    await act(async () => {
      await authContextLogin!({
        email: 'logged.in@university.edu',
        password: 'ValidPassword123!',
      });
    });

    expect(screen.getByTestId('status').textContent).toBe('authenticated');
    expect(screen.getByTestId('email').textContent).toBe('logged.in@university.edu');
    expect(authStorage.getRefreshToken()).toBe('login-refresh-token');
  });

  it('performs logout, revokes backend session, and cleans local credentials', async () => {
    authStorage.setRefreshToken('active-rt');
    vi.spyOn(authApi, 'refreshSession').mockResolvedValue({
      access_token: 'active-jwt',
      refresh_token: 'active-rt',
      token_type: 'bearer',
      expires_in: 1800,
    });
    vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue({
      user: {
        id: 'u-1',
        email: 'logout@uni.edu',
        full_name: 'Logout User',
        account_status: 'active',
        is_active: true,
        role_id: 'r-1',
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      role: {
        id: 'r-1',
        code: 'ROLE_STAFF',
        name: 'Staff',
        description: 'Staff',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      session_id: 's-1',
    });
    const mockLogoutSpy = vi.spyOn(authApi, 'logout').mockResolvedValue({
      status: 'success',
      message: 'Revoked',
    });

    const LogoutTestComponent: React.FC = () => {
      const { logout, status } = useAuth();
      return (
        <div>
          <div data-testid="status">{status}</div>
          <button onClick={() => logout()}>Perform Logout</button>
        </div>
      );
    };

    render(
      <AuthProvider>
        <LogoutTestComponent />
      </AuthProvider>
    );

    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      screen.getByText('Perform Logout').click();
    });

    expect(mockLogoutSpy).toHaveBeenCalled();
    expect(screen.getByTestId('status').textContent).toBe('unauthenticated');
    expect(authStorage.getRefreshToken()).toBeNull();
  });
});
