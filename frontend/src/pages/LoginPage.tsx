import React, { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Shield } from 'lucide-react';
import { useAuth } from '../auth/useAuth';
import { sanitizeInternalRedirect } from '../auth/auth.utils';
import { LoginForm } from '../components/auth/LoginForm';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import { StatutoryNotice } from '../components/ui/StatutoryNotice';
import { AuthLoadingState } from '../components/auth/AuthLoadingState';

export const LoginPage: React.FC = () => {
  const { status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (status === 'authenticated') {
      interface LocationState {
        from?: {
          pathname?: string;
          search?: string;
        };
      }
      const state = location.state as LocationState | null;
      const targetPath = state?.from?.pathname
        ? `${state.from.pathname}${state.from.search || ''}`
        : '/';
      navigate(sanitizeInternalRedirect(targetPath), { replace: true });
    }
  }, [status, navigate, location]);

  if (status === 'initializing') {
    return <AuthLoadingState />;
  }

  return (
    <div className="flex min-h-[85vh] flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-700 text-white shadow-md">
          <Shield className="h-8 w-8" />
        </div>
        <h1 className="mt-4 text-center text-2xl font-bold tracking-tight text-slate-900">
          E-WITNESS
        </h1>
        <p className="mt-1 text-center text-sm text-slate-500">
          Institutional Evidence Custody & Investigation Platform
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <Card className="shadow-sm border-slate-200">
          <CardHeader className="pb-4">
            <CardTitle>Sign in to your account</CardTitle>
            <CardDescription>
              Enter your verified institutional credentials to access your assigned departmental workspace.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LoginForm />
          </CardContent>
        </Card>

        <div className="mt-8">
          <StatutoryNotice />
        </div>
      </div>
    </div>
  );
};
