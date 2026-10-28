import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Lock, Mail, ShieldAlert } from 'lucide-react';
import { useAuth } from '../../auth/useAuth';
import { sanitizeInternalRedirect } from '../../auth/auth.utils';
import { Button } from '../ui/Button';
import { Alert } from '../ui/Alert';
import { ApiError } from '../../types/api';

export const LoginForm: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [touched, setTouched] = useState<{ email?: boolean; password?: boolean }>({});

  // Inline validation
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const isEmailValid = email.trim().length >= 5 && emailRegex.test(email.trim());
  const isPasswordValid = password.length >= 1;

  const emailError = touched.email && !isEmailValid ? 'Please enter a valid institutional email address.' : null;
  const passwordError = touched.password && !isPasswordValid ? 'Password credential is required.' : null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched({ email: true, password: true });

    if (!isEmailValid || !isPasswordValid || isSubmitting) {
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      await login({
        email: email.trim(),
        password,
      });

      // Navigate to safe return route or default dashboard
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
      const safeRedirect = sanitizeInternalRedirect(targetPath);
      navigate(safeRedirect, { replace: true });
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.code === 'NETWORK_ERROR' || err.status === 0 || err.status >= 500) {
          setErrorMessage('Authentication service is temporarily unavailable. Please try again.');
        } else if (err.code === 'ACCOUNT_PENDING_VERIFICATION') {
          setErrorMessage('Account email verification is required before sign in. Please verify your email.');
        } else if (err.code === 'ACCOUNT_INACTIVE') {
          setErrorMessage('Account is suspended or deactivated. Contact your department administrator.');
        } else {
          setErrorMessage('Sign-in failed. Check your credentials or contact your system administrator.');
        }
      } else {
        setErrorMessage('Sign-in failed. Check your credentials or contact your system administrator.');
      }
      // Clear password field on failed attempt
      setPassword('');
      setTouched((prev) => ({ ...prev, password: false }));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      {errorMessage && (
        <Alert variant="error" title="Authentication Error">
          {errorMessage}
        </Alert>
      )}

      <div>
        <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1.5">
          Institutional Email
        </label>
        <div className="relative rounded-lg shadow-sm">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-400">
            <Mail className="h-4 w-4" />
          </div>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={() => setTouched((prev) => ({ ...prev, email: true }))}
            aria-invalid={!!emailError}
            aria-describedby={emailError ? 'email-error' : undefined}
            disabled={isSubmitting}
            placeholder="investigator@institution.edu"
            className={`block w-full rounded-lg border py-2 pl-9 pr-3 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-offset-1 transition-colors ${
              emailError
                ? 'border-rose-400 focus:border-rose-500 focus:ring-rose-500'
                : 'border-slate-300 focus:border-indigo-500 focus:ring-indigo-500'
            } disabled:bg-slate-50 disabled:text-slate-500`}
          />
        </div>
        {emailError && (
          <p id="email-error" className="mt-1.5 text-xs text-rose-600 font-medium">
            {emailError}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-1.5">
          Password Credential
        </label>
        <div className="relative rounded-lg shadow-sm">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-400">
            <Lock className="h-4 w-4" />
          </div>
          <input
            id="password"
            name="password"
            type={showPassword ? 'text' : 'password'}
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onBlur={() => setTouched((prev) => ({ ...prev, password: true }))}
            aria-invalid={!!passwordError}
            aria-describedby={passwordError ? 'password-error' : undefined}
            disabled={isSubmitting}
            placeholder="••••••••••••"
            className={`block w-full rounded-lg border py-2 pl-9 pr-10 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-offset-1 transition-colors ${
              passwordError
                ? 'border-rose-400 focus:border-rose-500 focus:ring-rose-500'
                : 'border-slate-300 focus:border-indigo-500 focus:ring-indigo-500'
            } disabled:bg-slate-50 disabled:text-slate-500`}
          />
          <button
            type="button"
            onClick={() => setShowPassword((prev) => !prev)}
            aria-label={showPassword ? 'Hide password' : 'Show password'}
            className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600 focus:outline-none"
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {passwordError && (
          <p id="password-error" className="mt-1.5 text-xs text-rose-600 font-medium">
            {passwordError}
          </p>
        )}
      </div>

      <div className="pt-1">
        <Button
          type="submit"
          variant="primary"
          size="md"
          className="w-full justify-center"
          isLoading={isSubmitting}
        >
          Sign In
        </Button>
      </div>

      <div className="flex items-center gap-2 pt-2 text-xs text-slate-500 justify-center">
        <ShieldAlert className="h-3.5 w-3.5 text-slate-400" />
        <span>Institutional access only. All activities are audited.</span>
      </div>
    </form>
  );
};
