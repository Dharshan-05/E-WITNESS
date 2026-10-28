import { createBrowserRouter } from 'react-router-dom';
import { AppLayout } from '../components/layout/AppLayout';
import {
  HomePage,
  IncidentsPlaceholderPage,
  CasesPlaceholderPage,
  EvidencePlaceholderPage,
  AuditPlaceholderPage,
  HealthPage,
  NotFoundPage,
} from '../pages';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      {
        index: true,
        element: <HomePage />,
      },
      {
        path: 'incidents',
        element: <IncidentsPlaceholderPage />,
      },
      {
        path: 'cases',
        element: <CasesPlaceholderPage />,
      },
      {
        path: 'evidence',
        element: <EvidencePlaceholderPage />,
      },
      {
        path: 'audit',
        element: <AuditPlaceholderPage />,
      },
      {
        path: 'health',
        element: <HealthPage />,
      },
      {
        path: '*',
        element: <NotFoundPage />,
      },
    ],
  },
]);
