import React, { useState, useEffect, useCallback } from 'react';
import {
  Film,
  Lock,
  Copy,
  Check,
  RefreshCw,
  AlertTriangle,
  ShieldCheck,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { VideoPlayer } from './VideoPlayer';
import { AIAnnotationOverlay } from './AIAnnotationOverlay';
import { AISegmentsList } from './AISegmentsList';
import { AISegmentReviewModal } from './AISegmentReviewModal';
import { AISegmentHistoryModal } from './AISegmentHistoryModal';
import type {
  CaseEvidenceItemRead,
  CaseAISegmentRead,
  CaseAISegmentReviewRequest,
} from '../../types/case';
import {
  listCaseEvidenceAISegments,
  reviewCaseAISegment,
  overrideCaseAISegment,
  createCaseFinding,
} from '../../api/case';
import { getAttachmentDownloadUrl } from '../../api/evidence';
import { useAuth } from '../../auth';

interface VideoEvidenceReviewModalProps {
  caseId: string;
  evidenceItem: CaseEvidenceItemRead;
  incidentId?: string;
  isOpen: boolean;
  onClose: () => void;
  onRefreshCase?: () => void;
}

export const VideoEvidenceReviewModal: React.FC<VideoEvidenceReviewModalProps> = ({
  caseId,
  evidenceItem,
  incidentId,
  isOpen,
  onClose,
  onRefreshCase,
}) => {
  const { user } = useAuth();

  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [isLoadingUrl, setIsLoadingUrl] = useState<boolean>(true);
  const [urlError, setUrlError] = useState<string | null>(null);

  const [segments, setSegments] = useState<CaseAISegmentRead[]>([]);
  const [, setIsLoadingSegments] = useState<boolean>(true);

  const [currentTime, setCurrentTime] = useState<number>(0);
  const [activeSegmentForReview, setActiveSegmentForReview] = useState<CaseAISegmentRead | null>(
    null
  );
  const [activeSegmentForHistory, setActiveSegmentForHistory] = useState<CaseAISegmentRead | null>(
    null
  );
  const [copiedHash, setCopiedHash] = useState<boolean>(false);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);

  const roleCode = user?.role?.code;
  const isSupervisor =
    roleCode === 'ROLE_DEPT_ADMIN' ||
    roleCode === 'ROLE_SUPER_ADMIN' ||
    roleCode === 'department_admin' ||
    roleCode === 'super_admin';

  // 1. Fetch short-lived presigned URL
  const fetchDownloadUrl = useCallback(async () => {
    if (!incidentId) {
      setUrlError('No linked incident found for this evidence item.');
      setIsLoadingUrl(false);
      return;
    }

    setIsLoadingUrl(true);
    setUrlError(null);

    try {
      const resp = await getAttachmentDownloadUrl(incidentId, evidenceItem.evidence_id, 300);
      setDownloadUrl(resp.download_url);
      setExpiresAt(resp.expires_at);
    } catch (err: unknown) {
      setUrlError(
        err instanceof Error ? err.message : 'Failed to generate authorized streaming URL.'
      );
    } finally {
      setIsLoadingUrl(false);
    }
  }, [incidentId, evidenceItem.evidence_id]);

  // 2. Fetch linked AI Candidate Segments
  const fetchSegments = useCallback(async () => {
    setIsLoadingSegments(true);
    try {
      const items = await listCaseEvidenceAISegments(caseId, evidenceItem.evidence_id);
      setSegments(items);
    } catch {
      // Fallback: segments may be empty
      setSegments([]);
    } finally {
      setIsLoadingSegments(false);
    }
  }, [caseId, evidenceItem.evidence_id]);

  useEffect(() => {
    if (isOpen) {
      fetchDownloadUrl();
      fetchSegments();
    }
  }, [isOpen, fetchDownloadUrl, fetchSegments]);

  // Seek video to specific timestamp
  const handleSeekTo = (seconds: number) => {
    if (videoElement) {
      videoElement.currentTime = seconds;
      setCurrentTime(seconds);
    }
  };

  // Copy SHA-256 hash to clipboard
  const handleCopyHash = () => {
    if (evidenceItem.sha256_hash) {
      navigator.clipboard.writeText(evidenceItem.sha256_hash);
      setCopiedHash(true);
      setTimeout(() => setCopiedHash(false), 2000);
    }
  };

  // Submit human review decision
  const handleSubmitReview = async (
    payload: CaseAISegmentReviewRequest,
    createFindingPayload?: {
      findingType: string;
      title: string;
      description: string;
    }
  ) => {
    if (!activeSegmentForReview) return;

    const segmentId = activeSegmentForReview.segment_id || activeSegmentForReview.id;

    if (payload.is_override) {
      await overrideCaseAISegment(caseId, segmentId, payload);
    } else {
      await reviewCaseAISegment(caseId, segmentId, payload);
    }

    // If requested, also record a formal case finding
    if (createFindingPayload) {
      await createCaseFinding(caseId, {
        finding_type: createFindingPayload.findingType,
        title: createFindingPayload.title,
        description: createFindingPayload.description,
        evidence_ids: [evidenceItem.evidence_id],
        ai_segment_ids: [segmentId],
        incident_ids: incidentId ? [incidentId] : [],
        is_preliminary: true,
      });
    }

    // Refresh segments and case
    await fetchSegments();
    if (onRefreshCase) {
      onRefreshCase();
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-slate-950/80 backdrop-blur-sm overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="video-review-title"
    >
      <div className="w-full max-w-6xl bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[92vh]">
        {/* Modal Header & Verified Evidence Integrity Bar */}
        <div className="p-4 sm:px-6 bg-slate-900 border-b border-slate-800 text-white flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Film className="h-5 w-5 text-indigo-400 shrink-0" />
              <h3
                id="video-review-title"
                className="text-base font-bold text-white truncate"
              >
                {evidenceItem.file_name}
              </h3>
              <Badge
                variant={evidenceItem.integrity_status === 'verified' ? 'success' : 'danger'}
                size="sm"
                className="flex items-center gap-1"
              >
                <ShieldCheck className="h-3 w-3" />
                {evidenceItem.integrity_status.toUpperCase()}
              </Badge>
              {evidenceItem.is_legal_hold && (
                <Badge variant="purple" size="sm" className="flex items-center gap-1">
                  <Lock className="h-3 w-3" />
                  LEGAL HOLD ACTIVE
                </Badge>
              )}
            </div>

            {/* SHA-256 Digest & Custody Metadata */}
            <div className="flex items-center gap-3 text-xs text-slate-400 flex-wrap">
              <span className="font-mono text-[11px] text-slate-300 flex items-center gap-1">
                SHA-256: {evidenceItem.sha256_hash.slice(0, 16)}…
                <button
                  type="button"
                  onClick={handleCopyHash}
                  title="Copy full SHA-256 digest"
                  className="p-1 hover:text-white transition-colors"
                >
                  {copiedHash ? (
                    <Check className="h-3 w-3 text-emerald-400" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                </button>
              </span>
              <span>•</span>
              <span>{(evidenceItem.file_size_bytes / (1024 * 1024)).toFixed(2)} MB</span>
              <span>•</span>
              <span className="font-mono">{evidenceItem.content_type}</span>
              <span>•</span>
              <span>Custody Events: {evidenceItem.chain_of_custody_events_count}</span>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={fetchDownloadUrl}
              title="Refresh short-lived streaming URL"
              className="text-xs text-slate-300 border-slate-700 hover:text-white"
            >
              <RefreshCw className="h-3.5 w-3.5 mr-1" />
              Refresh URL
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
              className="text-slate-400 hover:text-white text-lg leading-none p-1.5"
            >
              ×
            </Button>
          </div>
        </div>

        {/* Modal Main Content: Split Grid (Player 60% / Segments 40%) */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 bg-slate-100">
          {/* Left Column: Video Evidence Player & Active AI Overlay */}
          <div className="lg:col-span-7 flex flex-col gap-4">
            {urlError && (
              <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-800 text-xs flex items-start gap-2">
                <AlertTriangle className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-semibold">Unable to authorize video playback</p>
                  <p>{urlError}</p>
                </div>
              </div>
            )}

            <div className="relative">
              <VideoPlayer
                src={downloadUrl}
                filename={evidenceItem.file_name}
                contentType={evidenceItem.content_type}
                isLoadingUrl={isLoadingUrl}
                urlExpiresAt={expiresAt}
                onRefreshUrl={fetchDownloadUrl}
                segments={segments}
                onSelectSegment={(seg) => setActiveSegmentForReview(seg)}
                onTimeUpdate={(t) => setCurrentTime(t)}
                videoRefCallback={(el) => setVideoElement(el)}
              />

              {/* Synchronized Real-Time Annotation Overlay on top of Video */}
              <AIAnnotationOverlay
                currentTime={currentTime}
                segments={segments}
                onSelectSegment={(seg) => setActiveSegmentForReview(seg)}
              />
            </div>

            {/* Quick Keyboard Shortcuts Reference Card */}
            <div className="p-3 bg-white rounded-xl border border-slate-200 text-[11px] text-slate-500 flex items-center justify-between gap-2 flex-wrap">
              <span className="font-semibold text-slate-700">Keyboard Shortcuts:</span>
              <div className="flex items-center gap-2 flex-wrap">
                <kbd className="px-1.5 py-0.5 bg-slate-100 rounded border border-slate-300 font-mono text-[10px]">
                  Space
                </kbd>{' '}
                Play/Pause
                <kbd className="px-1.5 py-0.5 bg-slate-100 rounded border border-slate-300 font-mono text-[10px]">
                  ← / →
                </kbd>{' '}
                Seek 5s
                <kbd className="px-1.5 py-0.5 bg-slate-100 rounded border border-slate-300 font-mono text-[10px]">
                  j / l
                </kbd>{' '}
                Seek 10s
                <kbd className="px-1.5 py-0.5 bg-slate-100 rounded border border-slate-300 font-mono text-[10px]">
                  m
                </kbd>{' '}
                Mute
                <kbd className="px-1.5 py-0.5 bg-slate-100 rounded border border-slate-300 font-mono text-[10px]">
                  f
                </kbd>{' '}
                Fullscreen
              </div>
            </div>
          </div>

          {/* Right Column: Synchronized Candidate Segments & Human Review */}
          <div className="lg:col-span-5 h-[520px] lg:h-auto flex flex-col">
            <AISegmentsList
              segments={segments}
              currentTime={currentTime}
              onSeekTo={handleSeekTo}
              onReviewSegment={(seg) => setActiveSegmentForReview(seg)}
              onViewHistory={(seg) => setActiveSegmentForHistory(seg)}
              canReview={true}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 bg-white border-t border-slate-200 flex items-center justify-between">
          <p className="text-xs text-slate-400">
            Institutional Chain of Custody & Advisory AI Video Verification UI
          </p>
          <Button variant="outline" size="sm" onClick={onClose}>
            Close Reviewer
          </Button>
        </div>
      </div>

      {/* Human Review Modal Dialog */}
      {activeSegmentForReview && (
        <AISegmentReviewModal
          segment={activeSegmentForReview}
          isOpen={!!activeSegmentForReview}
          onClose={() => setActiveSegmentForReview(null)}
          onSubmitReview={handleSubmitReview}
          isSupervisor={isSupervisor}
        />
      )}

      {/* Decision Audit History Modal */}
      {activeSegmentForHistory && (
        <AISegmentHistoryModal
          caseId={caseId}
          segment={activeSegmentForHistory}
          isOpen={!!activeSegmentForHistory}
          onClose={() => setActiveSegmentForHistory(null)}
        />
      )}
    </div>
  );
};
