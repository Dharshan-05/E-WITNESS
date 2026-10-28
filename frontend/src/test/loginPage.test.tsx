import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { LoginPage } from '../pages/LoginPage';
import { AuthProvider } from '../auth/AuthProvider';
import * as authApi from '../api/auth';
import { ApiError } from '../types/api';
import { authStorage } from '../auth/auth.storage';

const renderLoginPage = (initialRoute = '/login') => {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div data-testid="home-view">Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>
  );
};

describe('LoginPage & LoginForm UI', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    authStorage.clear();
  });

  it('renders institutional login page with branding and fields', async () => {
    renderLoginPage();

    expect(screen.getByRole('heading', { name: /E-WITNESS/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Sign in to your account/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Institutional Email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password Credential/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sign In/i })).toBeInTheDocument();
  });

  it('toggles password visibility between masked and plaintext', async () => {
    renderLoginPage();

    const passwordInput = screen.getByLabelText(/Password Credential/i);
    expect(passwordInput).toHaveAttribute('type', 'password');

    const toggleButton = screen.getByLabelText(/Show password/i);
    fireEvent.click(toggleButton);

    expect(passwordInput).toHaveAttribute('type', 'text');
    expect(screen.getByLabelText(/Hide password/i)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Hide password/i));
    expect(passwordInput).toHaveAttribute('type', 'password');
  });

  it('displays inline validation errors for invalid email and empty password', async () => {
    renderLoginPage();

    const emailInput = screen.getByLabelText(/Institutional Email/i);
    const submitButton = screen.getByRole('button', { name: /Sign In/i });

    // Blur empty email
    fireEvent.blur(emailInput);
    expect(await screen.findByText(/Please enter a valid institutional email address/i)).toBeInTheDocument();

    // Click submit
    fireEvent.click(submitButton);
    expect(await screen.findByText(/Password credential is required/i)).toBeInTheDocument();
  });

  it('submits valid credentials and navigates to target upon success', async () => {
    vi.spyOn(authApi, 'login').mockResolvedValue({
      access_token: 'valid-jwt',
      refresh_token: 'valid-rt',
      token_type: 'bearer',
      expires_in: 1800,
    });

    vi.spyOn(authApi, 'getCurrentUser').mockResolvedValue({
      user: {
        id: 'u-1',
        email: 'investigator@university.edu',
        full_name: 'Lead Detective',
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
      session_id: 'sess-1',
    });

    renderLoginPage();

    const emailInput = screen.getByLabelText(/Institutional Email/i);
    const passwordInput = screen.getByLabelText(/Password Credential/i);
    const submitButton = screen.getByRole('button', { name: /Sign In/i });

    fireEvent.change(emailInput, { target: { value: 'investigator@university.edu' } });
    fireEvent.change(passwordInput, { target: { value: 'CorrectPassword123!' } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(screen.getByTestId('home-view')).toBeInTheDocument();
    });
  });

  it('displays safe generic error message on invalid credentials without leaking password', async () => {
    vi.spyOn(authApi, 'login').mockRejectedValue(
      new ApiError(401, 'INVALID_CREDENTIALS', 'Invalid email or password.', 'req-test-999')
    );

    renderLoginPage();

    const emailInput = screen.getByLabelText(/Institutional Email/i);
    const passwordInput = screen.getByLabelText(/Password Credential/i);
    const submitButton = screen.getByRole('button', { name: /Sign In/i });

    fireEvent.change(emailInput, { target: { value: 'test@university.edu' } });
    fireEvent.change(passwordInput, { target: { value: 'WrongPassword!' } });
    fireEvent.click(submitButton);

    expect(
      await screen.findByText(/Sign-in failed. Check your credentials or contact your system administrator/i)
    ).toBeInTheDocument();

    // Password input cleared after failure
    expect(passwordInput).toHaveValue('');
  });

  it('displays safe network error message when server is unavailable', async () => {
    vi.spyOn(authApi, 'login').mockRejectedValue(
      new ApiError(0, 'NETWORK_ERROR', 'Failed to fetch', 'req-net-1')
    );

    renderLoginPage();

    const emailInput = screen.getByLabelText(/Institutional Email/i);
    const passwordInput = screen.getByLabelText(/Password Credential/i);
    const submitButton = screen.getByRole('button', { name: /Sign In/i });

    fireEvent.change(emailInput, { target: { value: 'test@university.edu' } });
    fireEvent.change(passwordInput, { target: { value: 'ValidPassword123!' } });
    fireEvent.click(submitButton);

    expect(
      await screen.findByText(/Authentication service is temporarily unavailable/i)
    ).toBeInTheDocument();
  });
});
