import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import App from '../App';
import { createTestRouter } from '../router/routes';
import { authStorage } from '../auth/auth.storage';
import * as authApi from '../api/auth';
import type { CurrentUserResponse, TokenResponse } from '../types/auth';

describe('App Root Component & Session Bootstrap', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    authStorage.clear();
  });

  afterEach(() => {
    authStorage.clear();
  });

  it('redirects to institutional login page with statutory notice when unauthenticated', async () => {
    render(<App routerOverride={createTestRouter(['/'])} />);

    // Wait for async auth resolution and redirect to /login
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Sign in to your account/i })).toBeInTheDocument();
    });

    // Branding in Header and Login Page
    expect(screen.getAllByText('E-WITNESS').length).toBeGreaterThan(0);

    // Field labels
    expect(screen.getByLabelText(/Institutional Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password Credential/i)).toBeInTheDocument();

    // Statutory notice in footer
    expect(
      screen.getByText(/probabilistic investigative leads/i)
    ).toBeInTheDocument();
  });

  it('renders application dashboard when valid session is restored', async () => {
    authStorage.setRefreshToken('valid-session-rt');

    const mockTokens: TokenResponse = {
      access_token: 'valid-jwt',
      refresh_token: 'refreshed-rt',
      token_type: 'bearer',
      expires_in: 1800,
    };

    const mockProfile: CurrentUserResponse = {
      user: {
        id: 'u-admin',
        email: 'supervisor@university.edu',
        full_name: 'Lead Supervisor',
        account_status: 'active',
        is_active: true,
        department_id: 'd-1',
        role_id: 'r-1',
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      role: {
        id: 'r-1',
        code: 'ROLE_DEPT_ADMIN',
        name: 'Department Administrator',
        description: 'Administrator',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      },
      session_id: 'sess-admin',
    };

    vi.spyOn(authApi, 'refreshSession').mockResolvedValue(mockTokens);
    vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue(mockProfile);

    render(<App routerOverride={createTestRouter(['/'])} />);

    await act(async () => {
      await Promise.resolve();
    });

    // Main header on Home page
    await waitFor(() => {
      expect(
        screen.getByText('Institutional Evidence & Investigation Workspace')
      ).toBeInTheDocument();
    });

    // Skip to main content link for accessibility
    expect(screen.getByText('Skip to main content')).toBeInTheDocument();

    // Module cards
    expect(screen.getByRole('heading', { name: 'Incident Intake & Triage' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Case Management' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Evidence Custody' })).toBeInTheDocument();

    // Authenticated user in Header
    expect(screen.getByText('Lead Supervisor')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sign Out/i })).toBeInTheDocument();
  });
});
