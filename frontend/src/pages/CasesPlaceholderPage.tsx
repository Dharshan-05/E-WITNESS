import React from 'react';
import { FolderLock, PlusCircle, ShieldCheck } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState } from '../components/ui/EmptyState';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';

export const CasesPlaceholderPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Investigation Cases & Custody Dossier"
        subtitle="Formal case lifecycle management, active investigator workloads, and audited supervisory reviews."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Cases' },
        ]}
        actions={
          <Button variant="primary" size="sm" leftIcon={<PlusCircle className="h-4 w-4" />} disabled>
            Initiate Case
          </Button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">State Machine</span>
              <Badge variant="default" size="sm">Phase 87</Badge>
            </div>
            <CardTitle>Formal Lifecycle</CardTitle>
            <CardDescription>
              Enforces transitions across DRAFT, OPEN, UNDER_INVESTIGATION, PENDING_SUPERVISOR_REVIEW, and CLOSED.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Governance</span>
              <Badge variant="danger" size="sm">Enforced</Badge>
            </div>
            <CardTitle>Separation of Duties</CardTitle>
            <CardDescription>
              Lead investigators are blocked from self-approving their own cases (`SELF_APPROVAL_PROHIBITED`).
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Disclosure</span>
              <Badge variant="purple" size="sm">Phase 89</Badge>
            </div>
            <CardTitle>Controlled Exports</CardTitle>
            <CardDescription>
              Tamper-evident disclosure manifests with canonical SHA-256 digests and complete credential stripping.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={<FolderLock className="h-6 w-6 text-slate-700" />}
            title="Case Dossier UI Scheduled for Phase 115"
            description="Phase 111 establishes core design tokens and client foundations. Interactive case dossier screens, note editors, finding recorders, and timeline components will be implemented in Phase 115."
            action={
              <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 px-3 py-1.5 rounded border border-slate-200">
                <ShieldCheck className="h-4 w-4 text-emerald-600" />
                <span>Backend Case Management APIs (Phases 81–90) Verified & Active</span>
              </div>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
};
