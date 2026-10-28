import React from 'react';
import { Home, ArrowLeft } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/Button';

export const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center px-4">
      <div className="rounded-full bg-slate-100 p-4 text-slate-500 mb-4">
        <span className="font-mono text-3xl font-extrabold text-slate-700">404</span>
      </div>
      <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
        Page or Resource Not Found
      </h1>
      <p className="mt-2 max-w-md text-sm text-slate-500 leading-normal">
        The requested path does not exist, or you lack departmental authorization to view this resource.
      </p>

      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate(-1)}
          leftIcon={<ArrowLeft className="h-4 w-4" />}
        >
          Go Back
        </Button>
        <Link to="/">
          <Button
            variant="primary"
            size="sm"
            leftIcon={<Home className="h-4 w-4" />}
          >
            Dashboard Overview
          </Button>
        </Link>
      </div>
    </div>
  );
};
