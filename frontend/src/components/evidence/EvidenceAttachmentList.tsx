import React from 'react';
import { Shield, FileCheck } from 'lucide-react';
import { Card, CardContent } from '../ui/Card';
import { Badge } from '../ui/Badge';
import type { EvidenceAttachmentRead } from '../../types/evidence';
import { formatFileSize } from '../../types/evidence';

interface EvidenceAttachmentListProps {
  attachments: EvidenceAttachmentRead[];
  /** Optional label for the section */
  title?: string;
}

/**
 * Summary list of completed evidence attachments with server-generated identifiers.
 */
export const EvidenceAttachmentList: React.FC<EvidenceAttachmentListProps> = ({
  attachments,
  title = 'Attached Evidence',
}) => {
  if (attachments.length === 0) return null;

  const getScanBadgeVariant = (
    status: string
  ): 'default' | 'primary' | 'success' | 'danger' | 'warning' => {
    switch (status) {
      case 'clean':
        return 'success';
      case 'infected':
      case 'quarantined':
        return 'danger';
      case 'failed':
        return 'warning';
      case 'scanning':
        return 'primary';
      default:
        return 'default';
    }
  };

  return (
    <div className="space-y-2" data-testid="evidence-attachment-list">
      <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
        <Shield className="h-3.5 w-3.5" />
        {title} ({attachments.length})
      </h3>
      <div className="space-y-1.5">
        {attachments.map((att) => (
          <Card key={att.id} className="border-slate-200">
            <CardContent className="p-3">
              <div className="flex items-center gap-3">
                <FileCheck className="h-4 w-4 text-emerald-600 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-900 truncate">
                      {att.original_filename}
                    </span>
                    <Badge variant={getScanBadgeVariant(att.scan_status)} size="sm">
                      {att.scan_status}
                    </Badge>
                  </div>
                  <div className="text-xs text-slate-500 flex items-center gap-3 mt-0.5">
                    <span>{formatFileSize(att.file_size_bytes)}</span>
                    <span className="font-mono">
                      {att.id.slice(0, 8)}…
                    </span>
                    {att.sha256_hash && (
                      <span className="font-mono text-[10px] text-slate-400" title={att.sha256_hash}>
                        SHA-256: {att.sha256_hash.slice(0, 12)}…
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};
