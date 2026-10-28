import React from 'react';
import { ShieldAlert, PlusCircle } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState } from '../components/ui/EmptyState';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';

export const IncidentsPlaceholderPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Incident Intake & Triage Workspace"
        subtitle="Department-isolated misconduct reporting, evidence linkage, and student disclosures."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Incidents' },
        ]}
        actions={
          <Button variant="primary" size="sm" leftIcon={<PlusCircle className="h-4 w-4" />} disabled>
            Report Incident
          </Button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Triage Queue</span>
              <Badge variant="default" size="sm">Phase 113</Badge>
            </div>
            <CardTitle>Intake & Verification</CardTitle>
            <CardDescription>
              Role-scoped triage queues for Student and Staff submissions with anonymous reporting protections.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Scope Isolation</span>
              <Badge variant="primary" size="sm">Hard Boundary</Badge>
            </div>
            <CardTitle>Department Isolation</CardTitle>
            <CardDescription>
              Backend enforces zero-leakage departmental boundaries. Unassigned incidents are strictly invisible.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Case Escalation</span>
              <Badge variant="success" size="sm">Phase 81</Badge>
            </div>
            <CardTitle>Case Escalation Link</CardTitle>
            <CardDescription>
              Triage reviews can escalate verified incidents directly into formal investigation cases (`CASE-YYYY-XXXXX`).
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={<ShieldAlert className="h-6 w-6 text-indigo-600" />}
            title="Incident Intake Interface Scheduled for Phase 113"
            description="Phase 111 establishes the architectural layout and typed API client. The full accessible incident submission form and department triage queue will be integrated in Phase 113."
          />
        </CardContent>
      </Card>
    </div>
  );
};
