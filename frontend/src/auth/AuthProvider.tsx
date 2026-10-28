import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AuthContext, type AuthContextValue } from './AuthContext';
import { authStorage } from './auth.storage';
import * as authApi from '../api/auth';
import { setAuthTokenGetter } from '../api/client';
import type {
  AuthenticatedUser,
  AuthStatus,
  Department,
  LoginCredentials,
  Role,
  RoleCode,
} from '../types/auth';

interface AuthProviderProps {
  children: React.ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [status, setStatus] = useState<AuthStatus>('initializing');
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [department, setDepartment] = useState<Department | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // In-memory access token storage (never saved to disk or localStorage)
  const accessTokenRef = useRef<string | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRefreshPromiseRef = useRef<Promise<boolean> | null>(null);
  const refreshSessionRef = useRef<() => Promise<boolean>>(() => Promise.resolve(false));

  // Register token provider with API client
  useEffect(() => {
    setAuthTokenGetter(() => accessTokenRef.current);
    return () => {
      setAuthTokenGetter(() => null);
    };
  }, []);

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, []);

  const scheduleTokenRefresh = useCallback(
    (expiresInSeconds: number) => {
      clearRefreshTimer();
      // Schedule refresh 60 seconds before expiration, with a minimum 10 second delay
      const refreshDelayMs = Math.max((expiresInSeconds - 60) * 1000, 10000);
      refreshTimerRef.current = setTimeout(async () => {
        try {
          await refreshSessionRef.current();
        } catch {
          // Failure handled inside refreshSessionInternal
        }
      }, refreshDelayMs);
    },
    [clearRefreshTimer]
  );

  const refreshSessionInternal = useCallback(async (): Promise<boolean> => {
    // Prevent duplicate concurrent refresh calls
    if (activeRefreshPromiseRef.current) {
      return activeRefreshPromiseRef.current;
    }

    const refreshToken = authStorage.getRefreshToken();
    if (!refreshToken) {
      accessTokenRef.current = null;
      setUser(null);
      setRole(null);
      setDepartment(null);
      setSessionId(null);
      setStatus('unauthenticated');
      return false;
    }

    const refreshPromise = (async () => {
      try {
        const tokenResp = await authApi.refreshSession(refreshToken);
        accessTokenRef.current = tokenResp.access_token;
        authStorage.setRefreshToken(tokenResp.refresh_token);

        // Introspect authenticated user profile
        const profile = await authApi.getCurrentUser(tokenResp.access_token);
        const authenticatedUser: AuthenticatedUser = {
          ...profile.user,
          role: profile.role,
          department: profile.department || null,
          session_id: profile.session_id,
        };

        setUser(authenticatedUser);
        setRole(profile.role);
        setDepartment(profile.department || null);
        setSessionId(profile.session_id);
        setError(null);
        setStatus('authenticated');

        scheduleTokenRefresh(tokenResp.expires_in);
        return true;
      } catch {
        clearRefreshTimer();
        accessTokenRef.current = null;
        authStorage.clear();
        setUser(null);
        setRole(null);
        setDepartment(null);
        setSessionId(null);
        setStatus('unauthenticated');
        return false;
      } finally {
        activeRefreshPromiseRef.current = null;
      }
    })();

    activeRefreshPromiseRef.current = refreshPromise;
    return refreshPromise;
  }, [clearRefreshTimer, scheduleTokenRefresh]);

  // Keep ref up to date
  useEffect(() => {
    refreshSessionRef.current = refreshSessionInternal;
  }, [refreshSessionInternal]);

  // Session restoration on mount
  useEffect(() => {
    let isMounted = true;

    async function initSession() {
      const storedRefreshToken = authStorage.getRefreshToken();
      if (!storedRefreshToken) {
        if (isMounted) {
          setStatus('unauthenticated');
        }
        return;
      }

      try {
        const success = await refreshSessionInternal();
        if (!success && isMounted) {
          setStatus('unauthenticated');
        }
      } catch {
        if (isMounted) {
          setStatus('unauthenticated');
        }
      }
    }

    initSession();

    return () => {
      isMounted = false;
      clearRefreshTimer();
    };
  }, [clearRefreshTimer, refreshSessionInternal]);

  const login = useCallback(
    async (credentials: LoginCredentials) => {
      setError(null);
      clearRefreshTimer();

      const tokenResp = await authApi.login(credentials);
      accessTokenRef.current = tokenResp.access_token;
      authStorage.setRefreshToken(tokenResp.refresh_token);

      try {
        const profile = await authApi.getCurrentUser(tokenResp.access_token);
        const authenticatedUser: AuthenticatedUser = {
          ...profile.user,
          role: profile.role,
          department: profile.department || null,
          session_id: profile.session_id,
        };

        setUser(authenticatedUser);
        setRole(profile.role);
        setDepartment(profile.department || null);
        setSessionId(profile.session_id);
        setStatus('authenticated');
        scheduleTokenRefresh(tokenResp.expires_in);
      } catch (profileErr) {
        // If profile fetch fails, treat login as aborted
        accessTokenRef.current = null;
        authStorage.clear();
        setStatus('unauthenticated');
        throw profileErr;
      }
    },
    [clearRefreshTimer, scheduleTokenRefresh]
  );

  const logout = useCallback(async () => {
    clearRefreshTimer();

    try {
      if (accessTokenRef.current) {
        await authApi.logout();
      }
    } catch {
      // Local cleanup proceeds regardless of network or 401 error
    } finally {
      accessTokenRef.current = null;
      authStorage.clear();
      setUser(null);
      setRole(null);
      setDepartment(null);
      setSessionId(null);
      setError(null);
      setStatus('unauthenticated');
    }
  }, [clearRefreshTimer]);

  const hasRole = useCallback(
    (requiredRoles: RoleCode | RoleCode[]): boolean => {
      if (!role) return false;
      const targetRoles = Array.isArray(requiredRoles) ? requiredRoles : [requiredRoles];
      const currentCode = role.code;

      return targetRoles.some((target) => {
        if (currentCode === target) return true;
        // Normalize strings for comparison (e.g. ROLE_STUDENT vs student)
        const normCurrent = currentCode.replace(/^ROLE_/i, '').toLowerCase();
        const normTarget = target.replace(/^ROLE_/i, '').toLowerCase();
        return normCurrent === normTarget;
      });
    },
    [role]
  );

  const value: AuthContextValue = {
    status,
    user,
    role,
    roleCode: role ? role.code : null,
    department,
    sessionId,
    error,
    login,
    logout,
    refreshSession: refreshSessionInternal,
    hasRole,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
