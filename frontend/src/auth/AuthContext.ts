import { createContext } from 'react';
import type {
  AuthenticatedUser,
  AuthStatus,
  Department,
  LoginCredentials,
  Role,
  RoleCode,
} from '../types/auth';

export interface AuthContextValue {
  status: AuthStatus;
  user: AuthenticatedUser | null;
  role: Role | null;
  roleCode: RoleCode | null;
  department: Department | null;
  sessionId: string | null;
  error: string | null;
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<boolean>;
  hasRole: (requiredRoles: RoleCode | RoleCode[]) => boolean;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
