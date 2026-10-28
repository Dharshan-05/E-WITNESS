import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { RequireAuth } from '../auth/RequireAuth';
import { sanitizeInternalRedirect } from '../auth/auth.utils';
import { AuthContext, type AuthContextValue } from '../auth/AuthContext';
import { UnauthorizedPage } from '../pages/UnauthorizedPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import type { AuthenticatedUser, Role } from '../types/auth';

const createMockAuthContext = (overrides: Partial<AuthContextValue> = {}): AuthContextValue => {
  return {
    status: 'unauthenticated',
    user: null,
    role: null,
    roleCode: null,
    department: null,
    sessionId: null,
    error: null,
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    refreshSession: vi.fn().mockResolvedValue(false),
    hasRole: vi.fn().mockReturnValue(false),
    ...overrides,
  };
};

const renderWithAuth = (
  authValue: AuthContextValue,
  initialRoute = '/protected'
) => {
  return render(
    <AuthContext.Provider value={authValue}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/login" element={<div data-testid="login-view">Login Page</div>} />
          <Route path="/unauthorized" element={<UnauthorizedPage />} />
          <Route path="/health" element={<div data-testid="health-view">Diagnostics</div>} />
          <Route
            path="/protected"
            element={
              <RequireAuth>
                <div data-testid="protected-content">Protected Content</div>
              </RequireAuth>
            }
          />
          <Route
            path="/cases"
            element={
              <RequireAuth allowedRoles={['ROLE_INVESTIGATOR', 'ROLE_DEPT_ADMIN']}>
                <div data-testid="cases-content">Cases Dossier</div>
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  );
};

describe('Protected Routes & Authorization Guards', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('sanitizeInternalRedirect security utility', () => {
    it('allows valid internal paths', () => {
      expect(sanitizeInternalRedirect('/cases')).toBe('/cases');
      expect(sanitizeInternalRedirect('/incidents?status=open')).toBe('/incidents?status=open');
      expect(sanitizeInternalRedirect('/')).toBe('/');
    });

    it('rejects external protocol-relative URLs (open redirect defense)', () => {
      expect(sanitizeInternalRedirect('//attacker.com')).toBe('/');
      expect(sanitizeInternalRedirect('//evil.org/phish')).toBe('/');
    });

    it('rejects non-relative external URLs or windows path separators', () => {
      expect(sanitizeInternalRedirect('https://attacker.com')).toBe('/');
      expect(sanitizeInternalRedirect('/\\attacker.com')).toBe('/');
      expect(sanitizeInternalRedirect(null)).toBe('/');
      expect(sanitizeInternalRedirect(123)).toBe('/');
    });
  });

  describe('Route guards', () => {
    it('redirects unauthenticated user from protected route to /login', () => {
      const mockAuth = createMockAuthContext({ status: 'unauthenticated' });
      renderWithAuth(mockAuth, '/protected');

      expect(screen.getByTestId('login-view')).toBeInTheDocument();
      expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
    });

    it('renders protected content for authenticated user', () => {
      const mockAuth = createMockAuthContext({
        status: 'authenticated',
        user: { id: 'u-1', email: 'test@uni.edu' } as AuthenticatedUser,
      });
      renderWithAuth(mockAuth, '/protected');

      expect(screen.getByTestId('protected-content')).toBeInTheDocument();
      expect(screen.queryByTestId('login-view')).not.toBeInTheDocument();
    });

    it('allows authorized role into role-guarded route', () => {
      const mockRole: Role = {
        id: 'r-1',
        code: 'ROLE_INVESTIGATOR',
        name: 'Investigator',
        description: 'Case Investigator',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      };

      const mockAuth = createMockAuthContext({
        status: 'authenticated',
        role: mockRole,
        roleCode: 'ROLE_INVESTIGATOR',
        hasRole: vi.fn().mockImplementation((roles) => roles.includes('ROLE_INVESTIGATOR')),
      });

      renderWithAuth(mockAuth, '/cases');

      expect(screen.getByTestId('cases-content')).toBeInTheDocument();
    });

    it('redirects unauthorized role to /unauthorized page', () => {
      const mockRole: Role = {
        id: 'r-student',
        code: 'ROLE_STUDENT',
        name: 'Student',
        description: 'Student',
        requires_department_scope: true,
        is_system_role: true,
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      };

      const mockUser: AuthenticatedUser = {
        id: 'u-student',
        email: 'student@university.edu',
        full_name: 'Student Jane',
        account_status: 'active',
        is_active: true,
        role: mockRole,
        session_id: 's-student',
        created_at: '2026-10-28T00:00:00Z',
        updated_at: '2026-10-28T00:00:00Z',
      };

      const mockAuth = createMockAuthContext({
        status: 'authenticated',
        user: mockUser,
        role: mockRole,
        roleCode: 'ROLE_STUDENT',
        hasRole: vi.fn().mockReturnValue(false),
      });

      renderWithAuth(mockAuth, '/cases');

      expect(screen.getByRole('heading', { name: /Access Denied/i })).toBeInTheDocument();
      expect(screen.getByText('student@university.edu')).toBeInTheDocument();
      expect(screen.queryByTestId('cases-content')).not.toBeInTheDocument();
    });

    it('allows access to public /health route without authentication', () => {
      const mockAuth = createMockAuthContext({ status: 'unauthenticated' });
      renderWithAuth(mockAuth, '/health');

      expect(screen.getByTestId('health-view')).toBeInTheDocument();
    });

    it('displays NotFoundPage for unknown routes', () => {
      const mockAuth = createMockAuthContext({ status: 'unauthenticated' });
      renderWithAuth(mockAuth, '/random-non-existent-page');

      expect(screen.getByText('404')).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: /Page or Resource Not Found/i })).toBeInTheDocument();
    });
  });
});
