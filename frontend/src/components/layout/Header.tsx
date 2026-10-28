import React from 'react';
import { Shield, Menu, X, Activity, LogOut, LogIn } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { Badge } from '../ui/Badge';
import { useAuth } from '../../auth/useAuth';

export interface HeaderProps {
  onToggleSidebar?: () => void;
  isSidebarOpen?: boolean;
}

export const Header: React.FC<HeaderProps> = ({ onToggleSidebar, isSidebarOpen = false }) => {
  const location = useLocation();
  const { status, user, role, logout } = useAuth();
  const envName = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_APP_ENV) || 'development';

  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-slate-200 bg-white px-4 sm:px-6 shadow-sm">
      <div className="flex items-center gap-3">
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            className="inline-flex items-center justify-center rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700 lg:hidden focus:outline-none focus:ring-2 focus:ring-indigo-500"
            aria-label="Toggle navigation menu"
          >
            {isSidebarOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        )}

        <Link to="/" className="flex items-center gap-2.5 font-bold tracking-tight text-slate-900 group">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm group-hover:bg-indigo-950 transition-colors">
            <Shield className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="flex flex-col">
            <span className="text-base font-bold leading-none text-slate-900 tracking-tight">E-WITNESS</span>
            <span className="text-[10px] font-medium tracking-wider text-slate-500 uppercase mt-0.5">
              Evidence Custody
            </span>
          </div>
        </Link>

        <div className="hidden sm:flex items-center ml-2">
          <Badge variant="default" size="sm" className="uppercase font-mono text-[10px] tracking-wider">
            {envName}
          </Badge>
        </div>
      </div>

      <div className="flex items-center gap-3 sm:gap-4">
        <Link
          to="/health"
          className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-md transition-colors ${
            location.pathname === '/health'
              ? 'bg-indigo-50 text-indigo-700 font-semibold'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          <Activity className="h-4 w-4 text-emerald-600" aria-hidden="true" />
          <span className="hidden md:inline">Diagnostics</span>
        </Link>

        <div className="h-4 w-px bg-slate-200" aria-hidden="true" />

        {status === 'authenticated' && user ? (
          <div className="flex items-center gap-2 sm:gap-3">
            <div className="flex flex-col items-end">
              <span className="text-xs font-semibold text-slate-900 leading-tight">
                {user.full_name || user.email}
              </span>
              <div className="flex items-center gap-1">
                <Badge variant="primary" size="sm" className="text-[9px] py-0 px-1 font-medium">
                  {role?.name || role?.code || 'User'}
                </Badge>
              </div>
            </div>

            <button
              type="button"
              onClick={() => logout()}
              title="Sign out of active session"
              className="inline-flex items-center gap-1 rounded-md p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-600 focus:outline-none focus:ring-2 focus:ring-rose-500 transition-colors"
              aria-label="Sign Out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <Link
            to="/login"
            className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-950 focus:outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm transition-colors"
          >
            <LogIn className="h-3.5 w-3.5" />
            <span>Sign In</span>
          </Link>
        )}
      </div>
    </header>
  );
};
