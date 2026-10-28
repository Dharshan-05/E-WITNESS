import React from 'react';
import {
  ShieldAlert,
  FolderLock,
  FileCheck2,
  Activity,
  ArrowRight,
  Lock,
  Cpu,
  KeyRound,
  FileBadge,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components/layout/PageHeader';
import { Card, CardHeader, CardTitle, CardDescription, CardFooter } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Alert } from '../components/ui/Alert';
import { Button } from '../components/ui/Button';
import { StatutoryNotice } from '../components/ui/StatutoryNotice';

export const HomePage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Institutional Evidence & Investigation Workspace"
        subtitle="Security-first incident reporting, digital evidence custody, and multi-department case investigation platform."
        actions={
          <Link to="/health">
            <Button variant="outline" size="sm" leftIcon={<Activity className="h-4 w-4 text-emerald-600" />}>
              Live Diagnostics
            </Button>
          </Link>
        }
      />

      <Alert variant="info" title="Phase 111 Frontend Foundation Initialized">
        You are viewing the architectural foundation of the E-WITNESS web client (Phase 111). Subsequent phases (112–120) introduce complete JWT session flows, incident intake wizards, case dossiers, and video annotation players.
      </Alert>

      {/* Primary Module Navigation Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        <Card className="hover:border-slate-300 transition-colors flex flex-col justify-between">
          <CardHeader>
            <div className="flex items-center justify-between mb-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
                <ShieldAlert className="h-5 w-5" />
              </div>
              <Badge variant="primary" size="sm">Phase 113</Badge>
            </div>
            <CardTitle>Incident Intake & Triage</CardTitle>
            <CardDescription>
              Structured, accessible incident submission and department-scoped triage queues for campus misconduct.
            </CardDescription>
          </CardHeader>
          <CardFooter>
            <Link to="/incidents" className="w-full">
              <Button variant="ghost" size="sm" className="w-full justify-between" rightIcon={<ArrowRight className="h-4 w-4" />}>
                Explore Module
              </Button>
            </Link>
          </CardFooter>
        </Card>

        <Card className="hover:border-slate-300 transition-colors flex flex-col justify-between">
          <CardHeader>
            <div className="flex items-center justify-between mb-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-800">
                <FolderLock className="h-5 w-5" />
              </div>
              <Badge variant="default" size="sm">Phase 115</Badge>
            </div>
            <CardTitle>Case Management</CardTitle>
            <CardDescription>
              Centralized lifecycle state machines, lead assignment limits, multi-tier notes, and supervisory reviews.
            </CardDescription>
          </CardHeader>
          <CardFooter>
            <Link to="/cases" className="w-full">
              <Button variant="ghost" size="sm" className="w-full justify-between" rightIcon={<ArrowRight className="h-4 w-4" />}>
                Explore Module
              </Button>
            </Link>
          </CardFooter>
        </Card>

        <Card className="hover:border-slate-300 transition-colors flex flex-col justify-between">
          <CardHeader>
            <div className="flex items-center justify-between mb-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                <FileCheck2 className="h-5 w-5" />
              </div>
              <Badge variant="success" size="sm">Phase 114</Badge>
            </div>
            <CardTitle>Evidence Custody</CardTitle>
            <CardDescription>
              Tamper-evident object storage, immediate SHA-256 digest validation, and audited legal hold preservation.
            </CardDescription>
          </CardHeader>
          <CardFooter>
            <Link to="/evidence" className="w-full">
              <Button variant="ghost" size="sm" className="w-full justify-between" rightIcon={<ArrowRight className="h-4 w-4" />}>
                Explore Module
              </Button>
            </Link>
          </CardFooter>
        </Card>
      </div>

      {/* Mandatory Safety Invariants Section */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-bold text-slate-900 tracking-tight mb-4">
          Core Institutional & Security Governance Invariants
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
            <div className="flex items-center gap-2 font-semibold text-slate-900 text-sm mb-1">
              <Lock className="h-4 w-4 text-rose-600" />
              <span>Biometrics Disabled</span>
            </div>
            <p className="text-xs text-slate-500 leading-normal">
              Hard-coded fail-closed matching lock. Zero facial recognition, 1:N identification, or automated suspect tagging.
            </p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
            <div className="flex items-center gap-2 font-semibold text-slate-900 text-sm mb-1">
              <Cpu className="h-4 w-4 text-amber-600" />
              <span>Advisory AI Only</span>
            </div>
            <p className="text-xs text-slate-500 leading-normal">
              Model annotations are probabilistic leads. Zero autonomous closure or dispositive findings without human review.
            </p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
            <div className="flex items-center gap-2 font-semibold text-slate-900 text-sm mb-1">
              <KeyRound className="h-4 w-4 text-indigo-600" />
              <span>Zero Credential Leakage</span>
            </div>
            <p className="text-xs text-slate-500 leading-normal">
              Frontend never handles S3 credentials or signing keys. All access operates via short-lived presigned URLs.
            </p>
          </div>

          <div className="rounded-lg border border-slate-100 bg-slate-50 p-4">
            <div className="flex items-center gap-2 font-semibold text-slate-900 text-sm mb-1">
              <FileBadge className="h-4 w-4 text-emerald-600" />
              <span>Cryptographic Proof</span>
            </div>
            <p className="text-xs text-slate-500 leading-normal">
              Every evidence attachment and case export manifest is attested by canonical SHA-256 digests.
            </p>
          </div>
        </div>
      </div>

      <StatutoryNotice />
    </div>
  );
};
