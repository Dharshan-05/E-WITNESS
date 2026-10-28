import React from 'react';
import { AlertCircle, ShieldAlert } from 'lucide-react';
import type { CaseAISegmentRead } from '../../types/case';
import { formatTime } from './video.utils';

interface AIAnnotationOverlayProps {
  currentTime: number;
  segments: CaseAISegmentRead[];
  onSelectSegment?: (segment: CaseAISegmentRead) => void;
}

interface NormalizedBBox {
  ymin: number;
  xmin: number;
  ymax: number;
  xmax: number;
}

function extractBBox(seg: CaseAISegmentRead): NormalizedBBox | null {
  const meta = seg.original_ai_prediction || {};
  const bbox = (meta.bbox || meta.bounding_box) as number[] | undefined;
  if (Array.isArray(bbox) && bbox.length === 4) {
    const [ymin, xmin, ymax, xmax] = bbox;
    if (
      typeof ymin === 'number' &&
      typeof xmin === 'number' &&
      typeof ymax === 'number' &&
      typeof xmax === 'number'
    ) {
      return { ymin, xmin, ymax, xmax };
    }
  }
  return null;
}

export const AIAnnotationOverlay: React.FC<AIAnnotationOverlayProps> = ({
  currentTime,
  segments,
  onSelectSegment,
}) => {
  // Find segments active at the current playback timestamp
  const activeSegments = segments.filter(
    (seg) => currentTime >= seg.start_seconds && currentTime <= seg.end_seconds
  );

  if (activeSegments.length === 0) {
    return null;
  }

  return (
    <div className="absolute inset-0 pointer-events-none z-20 flex flex-col justify-between p-3">
      {/* Top Banner: Active AI Candidate Segment Announcement */}
      <div className="flex flex-col gap-1.5 items-start max-w-lg">
        {activeSegments.map((seg) => {
          const rawScorePct = ((seg.raw_score ?? seg.score) * 100).toFixed(1);
          const calibratedScorePct =
            seg.calibrated_score !== null && seg.calibrated_score !== undefined
              ? (seg.calibrated_score * 100).toFixed(1)
              : null;

          let badgeBorderColor = 'border-amber-500/80 bg-amber-950/85 text-amber-200';
          if (seg.review_status === 'confirmed') {
            badgeBorderColor = 'border-emerald-500/80 bg-emerald-950/85 text-emerald-200';
          } else if (seg.review_status === 'rejected') {
            badgeBorderColor = 'border-rose-500/80 bg-rose-950/85 text-rose-200';
          } else if (seg.review_status === 'inconclusive') {
            badgeBorderColor = 'border-slate-500/80 bg-slate-900/85 text-slate-200';
          } else if (seg.review_status === 'escalated') {
            badgeBorderColor = 'border-purple-500/80 bg-purple-950/85 text-purple-200';
          }

          const bbox = extractBBox(seg);

          return (
            <div
              key={seg.id}
              className={`pointer-events-auto rounded-lg border px-3 py-2 shadow-lg backdrop-blur-xs flex flex-col gap-1 text-xs ${badgeBorderColor}`}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="flex items-center gap-1 font-semibold tracking-wide uppercase text-[11px] text-amber-400">
                  <AlertCircle className="h-3.5 w-3.5" />
                  AI Candidate Segment (Advisory)
                </span>
                <span className="font-mono text-[10px] bg-black/40 px-1.5 py-0.5 rounded">
                  {formatTime(seg.start_seconds)} – {formatTime(seg.end_seconds)}
                </span>
                <span className="uppercase text-[10px] font-bold px-1.5 py-0.5 rounded bg-black/50">
                  Status: {seg.review_status}
                </span>
              </div>

              <div className="flex items-center gap-2 flex-wrap text-slate-300 text-[11px]">
                <span>
                  Label:{' '}
                  <strong className="text-white">
                    {seg.human_corrected_label || seg.label}
                  </strong>
                </span>
                <span>•</span>
                <span>
                  Model Confidence: <strong>{rawScorePct}%</strong> (uncalibrated)
                </span>
                {calibratedScorePct && (
                  <>
                    <span>•</span>
                    <span>
                      Calibrated: <strong>{calibratedScorePct}%</strong>
                    </span>
                  </>
                )}
              </div>

              {/* Statutory Non-Authoritative Notice */}
              <div className="flex items-center gap-1 text-[10px] text-amber-300/90 italic">
                <ShieldAlert className="h-3 w-3 shrink-0" />
                <span>
                  Probabilistic advisory finding. Does not determine guilt or liability.
                </span>
              </div>

              {onSelectSegment && (
                <button
                  type="button"
                  onClick={() => onSelectSegment(seg)}
                  className="mt-1 text-left text-[11px] font-medium underline text-indigo-300 hover:text-indigo-200"
                >
                  Inspect / Review Decision →
                </button>
              )}

              {/* Render Spatial Bounding Box if present in backend metadata */}
              {bbox && (
                <div
                  style={{
                    position: 'absolute',
                    top: `${bbox.ymin * 100}%`,
                    left: `${bbox.xmin * 100}%`,
                    width: `${(bbox.xmax - bbox.xmin) * 100}%`,
                    height: `${(bbox.ymax - bbox.ymin) * 100}%`,
                  }}
                  className="pointer-events-none border-2 border-dashed border-amber-400 bg-amber-500/10 rounded"
                >
                  <span className="absolute -top-5 left-0 text-[10px] font-mono bg-black/80 text-amber-300 px-1 rounded">
                    {seg.label} ({rawScorePct}%)
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
