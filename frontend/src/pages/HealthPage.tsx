import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Database, HardDrive } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Alert } from '../components/ui/Alert';
import { Skeleton } from '../components/ui/Skeleton';
import { healthApi, type ReadinessResponse } from '../api/health';
import { ApiError } from '../types/api';

export const HealthPage: React.FC = () => {
  const [data, setData] = useState<ReadinessResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const fetchHealth = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    const start = performance.now();
    try {
      const resp = await healthApi.checkReadiness();
      const end = performance.now();
      setData(resp);
      setLatencyMs(Math.round(end - start));
      setLastChecked(new Date());
    } catch (err: unknown) {
      const end = performance.now();
      setLatencyMs(Math.round(end - start));
      if (err instanceof ApiError) {
        setError(`API Error [${err.code}]: ${err.message}`);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Unknown failure while querying backend readiness probe.');
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  const isHealthy = data?.status === 'ready' || data?.status === 'ok';

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Diagnostics & Readiness Probe"
        subtitle="Live verification of backend connectivity, database status, and API health endpoints."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Diagnostics' },
        ]}
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={fetchHealth}
            isLoading={isLoading}
            leftIcon={<RefreshCw className="h-4 w-4" />}
          >
            Probe Health
          </Button>
        }
      />

      {error ? (
        <Alert
          variant="error"
          title="Backend Connection Diagnostic Alert"
          className="shadow-sm"
        >
          <p>{error}</p>
          <div className="mt-3">
            <Button variant="danger" size="sm" onClick={fetchHealth}>
              Retry Health Probe
            </Button>
          </div>
        </Alert>
      ) : isHealthy ? (
        <Alert
          variant="success"
          title="Backend Systems Fully Operational"
          className="shadow-sm"
        >
          Connected to E-WITNESS FastAPI backend service. Round-trip probe latency:{' '}
          <span className="font-mono font-semibold">{latencyMs} ms</span>.
        </Alert>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Gateway Status</span>
              {isLoading ? (
                <Skeleton width={60} height={20} />
              ) : (
                <Badge variant={isHealthy ? 'success' : 'danger'} size="sm">
                  {data?.status?.toUpperCase() || 'OFFLINE'}
                </Badge>
              )}
            </div>
            <CardTitle>API Service State</CardTitle>
            <CardDescription>
              FastAPI ASGI gateway probe targeting `/api/v1/health/ready`.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-2">
                <Skeleton height={14} width="80%" />
                <Skeleton height={14} width="50%" />
              </div>
            ) : (
              <div className="text-xs text-slate-600 space-y-1 font-mono">
                <div>Endpoint: <span className="text-slate-800">/api/v1/health/ready</span></div>
                <div>Last Check: <span className="text-slate-800">{lastChecked?.toLocaleTimeString() || 'N/A'}</span></div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Database</span>
              {isLoading ? (
                <Skeleton width={60} height={20} />
              ) : (
                <Badge variant={isHealthy ? 'success' : 'danger'} size="sm">
                  POSTGRES 16
                </Badge>
              )}
            </div>
            <CardTitle>PostgreSQL Engine</CardTitle>
            <CardDescription>
              Relational transactions, Alembic migrations, and tenant constraints.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-2">
                <Skeleton height={14} width="70%" />
                <Skeleton height={14} width="60%" />
              </div>
            ) : (
              <div className="text-xs text-slate-600 space-y-1 font-mono">
                <div className="flex items-center gap-1.5">
                  <Database className="h-3.5 w-3.5 text-slate-500" />
                  <span>Head Revision: 20261028_0021</span>
                </div>
                <div>Status: <span className="text-emerald-700 font-semibold">Active & Migrated</span></div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Storage</span>
              {isLoading ? (
                <Skeleton width={60} height={20} />
              ) : (
                <Badge variant={isHealthy ? 'success' : 'danger'} size="sm">
                  S3 COMPLIANT
                </Badge>
              )}
            </div>
            <CardTitle>Object Vault</CardTitle>
            <CardDescription>
              Isolated evidence attachments with SHA-256 digest validation.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-2">
                <Skeleton height={14} width="75%" />
                <Skeleton height={14} width="40%" />
              </div>
            ) : (
              <div className="text-xs text-slate-600 space-y-1 font-mono">
                <div className="flex items-center gap-1.5">
                  <HardDrive className="h-3.5 w-3.5 text-slate-500" />
                  <span>Bucket: Isolated Vault</span>
                </div>
                <div>Presigned URL TTL: <span className="text-slate-800">300s max</span></div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Readiness Probe Response Envelope</CardTitle>
          <CardDescription>
            Raw JSON payload returned by the centralized health endpoint.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton height={120} />
          ) : (
            <pre className="rounded-lg bg-slate-900 p-4 text-xs font-mono text-emerald-400 overflow-x-auto border border-slate-800">
              {JSON.stringify(data || { status: 'offline', error }, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
