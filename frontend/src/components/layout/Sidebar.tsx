import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  AlertTriangle,
  FolderLock,
  FileCheck2,
  ScrollText,
  BarChart3,
  Activity,
  Sliders,
  Lock,
} from 'lucide-react';
import { clsx } from 'clsx';
import { useAuth } from '../../auth';
import type { RoleCode } from '../../types/auth';

export interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

interface NavItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  allowedRoles?: RoleCode[];
}

const navigation: NavItem[] = [
  { name: 'Dashboard Overview', href: '/', icon: LayoutDashboard },
  { name: 'Incident Intake', href: '/incidents', icon: AlertTriangle },
  {
    name: 'Investigation Cases',
    href: '/cases',
    icon: FolderLock,
    allowedRoles: [
      'ROLE_INVESTIGATOR',
      'ROLE_DEPT_ADMIN',
      'ROLE_SUPER_ADMIN',
      'investigator',
      'department_admin',
      'super_admin',
    ],
  },
  {
    name: 'Evidence Custody',
    href: '/evidence',
    icon: FileCheck2,
    allowedRoles: [
      'ROLE_INVESTIGATOR',
      'ROLE_DEPT_ADMIN',
      'ROLE_SUPER_ADMIN',
      'investigator',
      'department_admin',
      'super_admin',
    ],
  },
  {
    name: 'Analytics & Metrics',
    href: '/analytics',
    icon: BarChart3,
    allowedRoles: [
      'ROLE_INVESTIGATOR',
      'ROLE_DEPT_ADMIN',
      'ROLE_SUPER_ADMIN',
      'investigator',
      'department_admin',
      'super_admin',
    ],
  },
  {
    name: 'Audit & Traceability',
    href: '/audit',
    icon: ScrollText,
    allowedRoles: ['ROLE_DEPT_ADMIN', 'ROLE_SUPER_ADMIN', 'department_admin', 'super_admin'],
  },
  {
    name: 'Administration',
    href: '/admin',
    icon: Sliders,
    allowedRoles: ['ROLE_DEPT_ADMIN', 'ROLE_SUPER_ADMIN', 'department_admin', 'super_admin'],
  },
  { name: 'System Diagnostics', href: '/health', icon: Activity },
];

export const Sidebar: React.FC<SidebarProps> = ({ isOpen = false, onClose }) => {
  let isAuthorized = (_roles: RoleCode[]) => true;
  try {
    const auth = useAuth();
    isAuthorized = (roles: RoleCode[]) => auth.hasRole(roles);
  } catch {
    // If rendered without AuthProvider in tests, show all
    isAuthorized = () => true;
  }

  const visibleNav = navigation.filter((item) => {
    if (!item.allowedRoles) return true;
    return isAuthorized(item.allowedRoles);
  });

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-sm lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-slate-200 bg-white transition-transform duration-200 ease-in-out lg:static lg:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-16 shrink-0 items-center px-6 border-b border-slate-100 lg:hidden">
          <span className="text-base font-bold text-slate-900">E-WITNESS Navigation</span>
        </div>

        <div className="flex flex-1 flex-col justify-between overflow-y-auto px-4 py-5">
          <nav className="space-y-1">
            <div className="px-2 pb-2 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
              Operations & Custody
            </div>
            {visibleNav.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.name}
                  to={item.href}
                  onClick={onClose}
                  className={({ isActive }) =>
                    clsx(
                      'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150',
                      isActive
                        ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-600/25'
                        : 'text-slate-700 hover:bg-slate-100/90 hover:text-slate-900'
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon
                        className={clsx(
                          'h-4.5 w-4.5 shrink-0 transition-colors',
                          isActive ? 'text-white' : 'text-slate-400 group-hover:text-indigo-600'
                        )}
                      />
                      <span className="truncate tracking-tight">{item.name}</span>
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          <div className="pt-6 border-t border-slate-100">
            <div className="rounded-lg bg-slate-50 p-3 border border-slate-200 text-xs">
              <div className="flex items-center gap-2 text-slate-700 font-medium mb-1">
                <Lock className="h-3.5 w-3.5 text-slate-500 shrink-0" />
                <span>Security Notice</span>
              </div>
              <p className="text-slate-500 text-[11px] leading-relaxed">
                Client route guards do not substitute for server authorization. Department isolation is strictly enforced.
              </p>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
};
