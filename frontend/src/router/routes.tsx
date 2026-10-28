import { createBrowserRouter, createMemoryRouter, type RouteObject } from 'react-router-dom';
import { AppLayout } from '../components/layout/AppLayout';
import { RequireAuth } from '../auth/RequireAuth';
import {
  HomePage,
  LoginPage,
  UnauthorizedPage,
  IncidentsPage,
  CasesPage,
  AnalyticsPage,
  EvidencePlaceholderPage,
  AuditPlaceholderPage,
  HealthPage,
  NotFoundPage,
} from '../pages';

export const appRoutes: RouteObject[] = [
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      {
        path: 'unauthorized',
        element: <UnauthorizedPage />,
      },
      {
        path: 'health',
        element: <HealthPage />,
      },
      // Protected routes: session authentication required
      {
        element: <RequireAuth />,
        children: [
          {
            index: true,
            element: <HomePage />,
          },
          {
            path: 'incidents',
            element: <IncidentsPage />,
          },
          {
            path: 'evidence',
            element: <EvidencePlaceholderPage />,
          },
          {
            path: 'cases',
            element: (
              <RequireAuth allowedRoles={['ROLE_INVESTIGATOR', 'ROLE_DEPT_ADMIN', 'ROLE_SUPER_ADMIN']}>
                <CasesPage />
              </RequireAuth>
            ),
          },
          {
            path: 'analytics',
            element: (
              <RequireAuth allowedRoles={['ROLE_INVESTIGATOR', 'ROLE_DEPT_ADMIN', 'ROLE_SUPER_ADMIN']}>
                <AnalyticsPage />
              </RequireAuth>
            ),
          },
          {
            path: 'audit',
            element: (
              <RequireAuth allowedRoles={['ROLE_DEPT_ADMIN', 'ROLE_SUPER_ADMIN']}>
                <AuditPlaceholderPage />
              </RequireAuth>
            ),
          },
        ],
      },
      {
        path: '*',
        element: <NotFoundPage />,
      },
    ],
  },
];

export const router = createBrowserRouter(appRoutes);

export function createTestRouter(initialEntries: string[] = ['/']) {
  return createMemoryRouter(appRoutes, { initialEntries });
}
