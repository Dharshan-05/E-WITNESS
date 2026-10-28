import React from 'react';
import { RouterProvider } from 'react-router-dom';
import { router } from './router/routes';
import { AuthProvider } from './auth/AuthProvider';
import { ErrorBoundary } from './components/ui/ErrorBoundary';

interface AppProps {
  routerOverride?: typeof router;
}

export const App: React.FC<AppProps> = ({ routerOverride }) => {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <RouterProvider router={routerOverride || router} />
      </AuthProvider>
    </ErrorBoundary>
  );
};

export default App;
