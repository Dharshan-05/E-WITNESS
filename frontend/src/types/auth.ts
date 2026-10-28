/**
 * Authentication and User Identity Types.
 * Matches backend `backend/app/schemas/auth.py` and `backend/app/core/identity.py`.
 */

export type RoleCode =
  | 'ROLE_STUDENT'
  | 'ROLE_STAFF'
  | 'ROLE_DEPT_ADMIN'
  | 'ROLE_INVESTIGATOR'
  | 'ROLE_SUPER_ADMIN'
  | 'student'
  | 'staff'
  | 'investigator'
  | 'department_admin'
  | 'super_admin';

export type AccountStatus =
  | 'active'
  | 'pending_verification'
  | 'suspended'
  | 'disabled'
  | 'deactivated';

export interface User {
  id: string;
  email: string;
  institutional_id?: string | null;
  full_name: string;
  account_status: AccountStatus;
  is_active: boolean;
  department_id?: string | null;
  role_id: string;
  verified_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Role {
  id: string;
  code: RoleCode;
  name: string;
  description: string;
  requires_department_scope: boolean;
  is_system_role: boolean;
  created_at: string;
  updated_at: string;
}

export interface Department {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CurrentUserResponse {
  user: User;
  role: Role;
  department?: Department | null;
  session_id: string;
}

export interface GenericActionResponse {
  status: string;
  message: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export type AuthStatus =
  | 'initializing'
  | 'authenticated'
  | 'unauthenticated'
  | 'error';

export interface AuthenticatedUser extends Omit<User, 'role_id'> {
  role: Role;
  department?: Department | null;
  session_id: string;
}
