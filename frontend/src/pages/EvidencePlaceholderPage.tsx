import React from 'react';
import { FileCheck2, UploadCloud, Lock } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState } from '../components/ui/EmptyState';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';

export const EvidencePlaceholderPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Digital Evidence Custody & Legal Hold"
        subtitle="Cryptographically verified evidence attachments, SHA-256 digests, and tamper-resistant retention holds."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Evidence' },
        ]}
        actions={
          <Button variant="primary" size="sm" leftIcon={<UploadCloud className="h-4 w-4" />} disabled>
            Upload Evidence
          </Button>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Integrity</span>
              <Badge variant="success" size="sm">SHA-256</Badge>
            </div>
            <CardTitle>Immutable Hashes</CardTitle>
            <CardDescription>
              All evidence bytes generate immediate cryptographic digests before entering isolated S3 storage buckets.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Retention Protection</span>
              <Badge variant="purple" size="sm">Phase 83</Badge>
            </div>
            <CardTitle>Legal Hold System</CardTitle>
            <CardDescription>
              Formal hold orders (`HOLD-YYYY-XXXXX`) strictly prevent unlinking or deletion across all lifecycles.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Chunked Streaming</span>
              <Badge variant="default" size="sm">Phase 114</Badge>
            </div>
            <CardTitle>Chunked Uploader</CardTitle>
            <CardDescription>
              Resumable, chunked client-side uploads with browser SHA-256 verification and presigned URL handoffs.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={<FileCheck2 className="h-6 w-6 text-emerald-600" />}
            title="Evidence Chunking & Verification UI Scheduled for Phase 114"
            description="Phase 111 establishes API contracts and layout foundations. Chunked multipart file streaming, client-side SHA-256 workers, and the interactive custody ledger will be integrated in Phase 114."
            action={
              <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 px-3 py-1.5 rounded border border-slate-200">
                <Lock className="h-4 w-4 text-slate-600" />
                <span>Zero Direct Storage Credentials in Client Memory</span>
              </div>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
};
