import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { StatutoryNotice } from '../ui/StatutoryNotice';

export const AppLayout: React.FC = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Skip to main content link for accessibility */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-slate-900 focus:px-4 focus:py-2 focus:text-sm focus:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
      >
        Skip to main content
      </a>

      <Header
        onToggleSidebar={() => setIsSidebarOpen((prev) => !prev)}
        isSidebarOpen={isSidebarOpen}
      />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />

        <div className="flex flex-1 flex-col overflow-y-auto">
          <main id="main-content" className="flex-1 px-4 py-6 sm:px-6 lg:px-8 max-w-7xl w-full mx-auto">
            <Outlet />
          </main>

          <footer className="border-t border-slate-200 bg-white px-4 py-6 sm:px-6 lg:px-8 mt-auto">
            <div className="max-w-7xl mx-auto space-y-4">
              <StatutoryNotice compact />
              <div className="flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-2">
                <span>
                  &copy; 2026 E-WITNESS Institutional Incident Custody Platform. All rights reserved.
                </span>
                <span className="font-mono text-[11px] text-slate-400">
                  Biometrics Matching Disabled Fail-Closed &middot; Zero 1:N Surveillance
                </span>
              </div>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
};
