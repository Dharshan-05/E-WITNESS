import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertOctagon, RotateCcw } from 'lucide-react';
import { Button } from './Button';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public override state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });
    // Safe client-side logging (excluding sensitive payloads)
    console.error('ErrorBoundary caught an unhandled UI render error:', error.message);
  }

  private handleReset = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  public override render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6">
          <div className="max-w-md w-full rounded-xl border border-rose-200 bg-white p-8 shadow-sm text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-rose-50 text-rose-600 mb-5">
              <AlertOctagon className="h-7 w-7" aria-hidden="true" />
            </div>
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">
              Application Render Error
            </h2>
            <p className="mt-2 text-sm text-slate-600 leading-normal">
              An unexpected interface error occurred. Security boundaries and backend data integrity remain fully protected.
            </p>
            {this.state.error?.message && (
              <div className="mt-4 rounded-md bg-slate-100 p-3 text-left font-mono text-xs text-slate-700 overflow-x-auto max-h-28 border border-slate-200">
                {this.state.error.message}
              </div>
            )}
            <div className="mt-6">
              <Button
                variant="primary"
                onClick={this.handleReset}
                leftIcon={<RotateCcw className="h-4 w-4" />}
                className="w-full"
              >
                Reload Interface
              </Button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
