import React from 'react';
import { ShieldAlert, ArrowLeft, LogOut } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Alert } from '../components/ui/Alert';

export const UnauthorizedPage: React.FC = () => {
  const { user, role, department, logout } = useAuth();

  return (
    <div className="mx-auto max-w-xl py-12 px-4 text-center">
      <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-rose-50 text-rose-600 border border-rose-100 shadow-sm">
        <ShieldAlert className="h-8 w-8" />
      </div>

      <h1 className="text-2xl font-bold tracking-tight text-slate-900 mb-2">
        Access Denied (403)
      </h1>
      <p className="text-sm text-slate-600 mb-6">
        Your authenticated institutional account does not possess the required role permissions or department scope to access this module.
      </p>

      {user && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-slate-50 p-4 text-left text-sm space-y-2">
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Active Identity Context
          </div>
          <div className="flex justify-between items-center py-1 border-b border-slate-200">
            <span className="text-slate-600">Principal:</span>
            <span className="font-medium text-slate-900">{user.email}</span>
          </div>
          <div className="flex justify-between items-center py-1 border-b border-slate-200">
            <span className="text-slate-600">Assigned Role:</span>
            <Badge variant="primary" size="sm">
              {role?.name || role?.code || 'Standard User'}
            </Badge>
          </div>
          {department && (
            <div className="flex justify-between items-center py-1">
              <span className="text-slate-600">Department Scope:</span>
              <span className="font-medium text-slate-900">{department.name}</span>
            </div>
          )}
        </div>
      )}

      <Alert variant="warning" className="text-left mb-6">
        Backend Role-Based Access Control (RBAC) and departmental isolation are authoritative. Contact your Department Administrator or Super Administrator to request elevation.
      </Alert>

      <div className="flex items-center justify-center gap-3">
        <Link to="/">
          <Button variant="outline" size="sm" leftIcon={<ArrowLeft className="h-4 w-4" />}>
            Return to Dashboard
          </Button>
        </Link>
        <Button
          variant="danger"
          size="sm"
          leftIcon={<LogOut className="h-4 w-4" />}
          onClick={() => logout()}
        >
          Sign Out
        </Button>
      </div>
    </div>
  );
};
