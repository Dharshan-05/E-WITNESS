import React, { useState } from 'react';
import { Shield, FileCheck, Play, Download, X } from 'lucide-react';
import { Card, CardContent } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import type { EvidenceAttachmentRead } from '../../types/evidence';
import { formatFileSize } from '../../types/evidence';
import { getAttachmentDownloadUrl } from '../../api/evidence';

interface EvidenceAttachmentListProps {
  attachments: EvidenceAttachmentRead[];
  /** Optional label for the section */
  title?: string;
}

/**
 * Summary list of completed evidence attachments with server-generated identifiers,
 * tamper-evident SHA-256 integrity display, and inline video playback / download.
 */
export const EvidenceAttachmentList: React.FC<EvidenceAttachmentListProps> = ({
  attachments,
  title = 'Attached Evidence',
}) => {
  const [activeVideoAttId, setActiveVideoAttId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [loadingVideoId, setLoadingVideoId] = useState<string | null>(null);

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

  const isVideoFile = (att: EvidenceAttachmentRead) => {
    const fn = (att.original_filename || '').toLowerCase();
    const mime = (att.declared_mime_type || '').toLowerCase();
    return fn.endsWith('.webm') || fn.endsWith('.mp4') || mime.startsWith('video/');
  };

  const handleTogglePlayVideo = async (att: EvidenceAttachmentRead) => {
    if (activeVideoAttId === att.id) {
      setActiveVideoAttId(null);
      setVideoUrl(null);
      return;
    }
    setLoadingVideoId(att.id);
    try {
      const res = await getAttachmentDownloadUrl(att.incident_id, att.id);
      setVideoUrl(res.download_url);
      setActiveVideoAttId(att.id);
    } catch (err) {
      console.error('Failed to retrieve video stream URL:', err);
    } finally {
      setLoadingVideoId(null);
    }
  };

  const handleDownload = async (att: EvidenceAttachmentRead) => {
    try {
      const res = await getAttachmentDownloadUrl(att.incident_id, att.id);
      window.open(res.download_url, '_blank');
    } catch (err) {
      console.error('Failed to download evidence attachment:', err);
    }
  };

  return (
    <div className="space-y-2" data-testid="evidence-attachment-list">
      <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
        <Shield className="h-3.5 w-3.5" />
        {title} ({attachments.length})
      </h3>
      <div className="space-y-1.5">
        {attachments.map((att) => {
          const isVideo = isVideoFile(att);
          const isPlaying = activeVideoAttId === att.id;

          return (
            <Card key={att.id} className="border-slate-200">
              <CardContent className="p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <FileCheck className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-slate-900 truncate">
                          {att.original_filename}
                        </span>
                        <Badge variant={getScanBadgeVariant(att.scan_status)} size="sm">
                          {att.scan_status}
                        </Badge>
                      </div>
                      <div className="text-xs text-slate-500 flex items-center gap-3 mt-0.5 flex-wrap">
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

                  <div className="flex items-center gap-1.5 shrink-0">
                    {isVideo && (
                      <Button
                        variant={isPlaying ? 'primary' : 'outline'}
                        size="sm"
                        className="text-xs h-7 px-2"
                        disabled={loadingVideoId === att.id}
                        onClick={() => handleTogglePlayVideo(att)}
                        title="Watch video evidence"
                      >
                        <Play className="h-3 w-3 mr-1 fill-current" />
                        {loadingVideoId === att.id ? 'Loading…' : isPlaying ? 'Hide' : 'Play'}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs h-7 px-2 text-slate-600 hover:text-slate-900"
                      onClick={() => handleDownload(att)}
                      title="Download original file"
                    >
                      <Download className="h-3 w-3" />
                    </Button>
                  </div>
                </div>

                {isPlaying && videoUrl && (
                  <div className="mt-3 rounded-lg overflow-hidden border border-slate-800 bg-black">
                    <div className="flex justify-between items-center px-3 py-1.5 bg-slate-900 text-xs text-slate-300">
                      <span className="truncate font-mono">{att.original_filename}</span>
                      <button
                        onClick={() => {
                          setActiveVideoAttId(null);
                          setVideoUrl(null);
                        }}
                        className="text-slate-400 hover:text-white p-0.5"
                        aria-label="Close video player"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <video
                      src={videoUrl}
                      controls
                      autoPlay
                      className="w-full max-h-72 object-contain bg-black"
                    />
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
};
