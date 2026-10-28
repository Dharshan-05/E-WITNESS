import { apiClient } from './client';
import type {
  CurrentUserResponse,
  GenericActionResponse,
  LoginCredentials,
  RefreshTokenRequest,
  TokenResponse,
} from '../types/auth';

/**
 * Authentication API module integrating with FastAPI backend.
 * Endpoints:
 * - POST /api/v1/auth/login
 * - POST /api/v1/auth/refresh
 * - POST /api/v1/auth/logout
 * - GET  /api/v1/auth/me
 */

/**
 * Authenticate institutional user credentials and establish session.
 */
export async function login(credentials: LoginCredentials): Promise<TokenResponse> {
  return apiClient.post<TokenResponse>('/auth/login', credentials);
}

/**
 * Rotate refresh token and obtain fresh access token.
 */
export async function refreshSession(refreshToken: string): Promise<TokenResponse> {
  const payload: RefreshTokenRequest = { refresh_token: refreshToken };
  return apiClient.post<TokenResponse>('/auth/refresh', payload);
}

/**
 * Introspect authenticated user profile, role, department, and session.
 * Optionally accepts an explicit access token (e.g. during session bootstrap).
 */
export async function getCurrentUser(token?: string): Promise<CurrentUserResponse> {
  return apiClient.get<CurrentUserResponse>('/auth/me', token ? { token } : undefined);
}

/**
 * Terminate active session and revoke principal tokens on the backend.
 */
export async function logout(): Promise<GenericActionResponse> {
  return apiClient.post<GenericActionResponse>('/auth/logout');
}
