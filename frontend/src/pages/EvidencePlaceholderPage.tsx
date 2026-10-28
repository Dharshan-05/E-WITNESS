import React, { useState, useEffect, useCallback } from 'react';
import { Lock, Search, RefreshCw } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import { EvidenceUploader, EvidenceAttachmentList } from '../components/evidence';
import { listAttachments } from '../api/evidence';
import type { EvidenceAttachmentRead } from '../types/evidence';

export const EvidencePlaceholderPage: React.FC = () => {
  const [incidentIdInput, setIncidentIdInput] = useState('');
  const [activeIncidentId, setActiveIncidentId] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<EvidenceAttachmentRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchIncidentEvidence = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await listAttachments(id);
      setAttachments(result);
    } catch {
      setError('Could not retrieve evidence records for this incident. Verify the ID and your permissions.');
      setAttachments([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleLookup = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = incidentIdInput.trim();
    if (!trimmed) return;
    setActiveIncidentId(trimmed);
  };

  useEffect(() => {
    if (activeIncidentId) {
      fetchIncidentEvidence(activeIncidentId);
    }
  }, [activeIncidentId, fetchIncidentEvidence]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Digital Evidence Custody & Upload Workspace"
        subtitle="Cryptographically verified evidence attachments, SHA-256 digests, chunked multipart uploads, and tamper-resistant custody records."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Evidence' },
        ]}
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
              All evidence files receive immediate SHA-256 cryptographic verification before entering isolated object storage.
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
              Formal hold orders strictly prevent evidence deletion or unlinking across all case and incident lifecycles.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-slate-500 uppercase">Chunked Streaming</span>
              <Badge variant="success" size="sm">Phase 114 Ready</Badge>
            </div>
            <CardTitle>Chunked Multipart Uploader</CardTitle>
            <CardDescription>
              Resumable, chunked client uploads via presigned URLs with progress reporting, cancellation, and validation.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      {/* Incident Evidence Explorer Card */}
      <Card>
        <CardHeader>
          <CardTitle>Evidence Attachment & Upload Console</CardTitle>
          <CardDescription>
            Specify an Incident UUID to inspect attached evidence or upload new digital files to the chain of custody.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <form onSubmit={handleLookup} className="flex gap-2 max-w-lg">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                type="text"
                value={incidentIdInput}
                onChange={(e) => setIncidentIdInput(e.target.value)}
                placeholder="Enter Incident UUID (e.g. 550e8400-e29b-41d4-a716-446655440000)"
                className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600 font-mono"
              />
            </div>
            <Button type="submit" variant="primary" size="sm">
              Load Evidence
            </Button>
          </form>

          {activeIncidentId && (
            <div className="space-y-6 pt-4 border-t border-slate-100">
              <div className="flex items-center justify-between bg-slate-50 p-3 rounded-lg border border-slate-200">
                <div className="flex items-center space-x-2 text-xs">
                  <span className="font-semibold text-slate-600">Active Incident:</span>
                  <span className="font-mono text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                    {activeIncidentId}
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => fetchIncidentEvidence(activeIncidentId)}
                  isLoading={loading}
                  className="text-xs"
                >
                  <RefreshCw className="h-3.5 w-3.5 mr-1" />
                  Refresh
                </Button>
              </div>

              {error && (
                <div className="text-xs text-rose-600 bg-rose-50 border border-rose-200 p-3 rounded-lg">
                  {error}
                </div>
              )}

              {/* Upload section */}
              <div className="space-y-2">
                <h3 className="text-xs font-bold text-slate-600 uppercase tracking-wider">
                  Upload Evidence to Incident
                </h3>
                <EvidenceUploader
                  incidentId={activeIncidentId}
                  onAttachmentsChange={(newItems) => {
                    setAttachments((prev) => [...prev, ...newItems]);
                  }}
                />
              </div>

              {/* Attached evidence */}
              <div className="space-y-2 pt-4 border-t border-slate-100">
                {attachments.length > 0 ? (
                  <EvidenceAttachmentList attachments={attachments} />
                ) : (
                  <p className="text-xs text-slate-400 italic">No evidence records currently attached to this incident.</p>
                )}
              </div>
            </div>
          )}

          {!activeIncidentId && (
            <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 px-3 py-2 rounded border border-slate-200">
              <Lock className="h-4 w-4 text-slate-600" />
              <span>Zero direct storage credentials stored in client memory. All uploads authenticate via short-lived presigned endpoints.</span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
