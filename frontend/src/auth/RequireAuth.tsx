import React from 'react';
import { Navigate, useLocation, Outlet } from 'react-router-dom';
import { useAuth } from './useAuth';
import { AuthLoadingState } from '../components/auth/AuthLoadingState';
import type { RoleCode } from '../types/auth';

interface RequireAuthProps {
  allowedRoles?: RoleCode[];
  children?: React.ReactNode;
}

export const RequireAuth: React.FC<RequireAuthProps> = ({ allowedRoles, children }) => {
  const { status, hasRole } = useAuth();
  const location = useLocation();

  if (status === 'initializing') {
    return <AuthLoadingState />;
  }

  if (status === 'unauthenticated' || status === 'error') {
    // Preserve current location for post-authentication redirect
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Role authorization check (UX guard; backend enforces authoritative RBAC)
  if (allowedRoles && allowedRoles.length > 0 && !hasRole(allowedRoles)) {
    return <Navigate to="/unauthorized" replace />;
  }

  return children ? <>{children}</> : <Outlet />;
};
