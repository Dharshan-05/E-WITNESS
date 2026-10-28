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
  Lock,
} from 'lucide-react';
import { clsx } from 'clsx';

export interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

interface NavItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  phase?: string;
}

const navigation: NavItem[] = [
  { name: 'Dashboard Overview', href: '/', icon: LayoutDashboard },
  { name: 'Incident Intake', href: '/incidents', icon: AlertTriangle, phase: 'Phase 113' },
  { name: 'Investigation Cases', href: '/cases', icon: FolderLock, phase: 'Phase 115' },
  { name: 'Evidence Custody', href: '/evidence', icon: FileCheck2, phase: 'Phase 114' },
  { name: 'Analytics & Metrics', href: '/analytics', icon: BarChart3, phase: 'Phase 117' },
  { name: 'Audit & Traceability', href: '/audit', icon: ScrollText, phase: 'Phase 118' },
  { name: 'System Diagnostics', href: '/health', icon: Activity },
];

export const Sidebar: React.FC<SidebarProps> = ({ isOpen = false, onClose }) => {
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
            {navigation.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.name}
                  to={item.href}
                  onClick={onClose}
                  className={({ isActive }) =>
                    clsx(
                      'group flex items-center justify-between rounded-md px-3 py-2 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-slate-900 text-white shadow-sm'
                        : 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <div className="flex items-center gap-3">
                        <Icon
                          className={clsx(
                            'h-4 w-4 shrink-0',
                            isActive ? 'text-white' : 'text-slate-500 group-hover:text-slate-700'
                          )}
                        />
                        <span>{item.name}</span>
                      </div>
                      {item.phase && (
                        <span
                          className={clsx(
                            'text-[10px] font-mono px-1.5 py-0.5 rounded',
                            isActive ? 'bg-slate-800 text-slate-300' : 'bg-slate-100 text-slate-500'
                          )}
                        >
                          {item.phase}
                        </span>
                      )}
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
