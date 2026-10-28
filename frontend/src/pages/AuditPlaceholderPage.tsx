import React from 'react';
import { ScrollText, Database } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState } from '../components/ui/EmptyState';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';

export const AuditPlaceholderPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Security Audit & Operational Traceability"
        subtitle="Append-only cryptographic event ledger, case timeline integration, and access monitoring."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Audit Trail' },
        ]}
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Cryptographic Chain</span>
              <Badge variant="default" size="sm">Phase 13</Badge>
            </div>
            <CardTitle>Merkle-Linked Audit</CardTitle>
            <CardDescription>
              Each audit entry binds sequence number, SHA-256 event hash, and previous event digest.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Relational Linkage</span>
              <Badge variant="success" size="sm">Phase 90</Badge>
            </div>
            <CardTitle>Structured Case Linkage</CardTitle>
            <CardDescription>
              Direct `case_id` column indexes all case-associated events for fast, deterministic timeline retrieval.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Traceability UI</span>
              <Badge variant="primary" size="sm">Phase 118</Badge>
            </div>
            <CardTitle>Audit Viewer Console</CardTitle>
            <CardDescription>
              Dedicated filtering interface for security administrators with cursor pagination and export support.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={<ScrollText className="h-6 w-6 text-indigo-600" />}
            title="Audit Viewer Console Scheduled for Phase 118"
            description="Phase 111 establishes the data contracts and type safety. Full search, filtering, actor auditing, and timeline visualization tables will be implemented in Phase 118."
            action={
              <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 px-3 py-1.5 rounded border border-slate-200">
                <Database className="h-4 w-4 text-slate-600" />
                <span className="font-mono">SecurityAuditEvent Ledger Active (21 Alembic Migrations Applied)</span>
              </div>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
};
