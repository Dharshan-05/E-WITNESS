/**
 * AI Candidate Segment & Advisory Invariants.
 * Matches backend `backend/app/core/case.py` and `ai.py`.
 */

export const AI_ADVISORY_DISCLAIMER =
  'AI violence detection annotations are probabilistic investigative leads only, ' +
  'not dispositive of guilt or wrongdoing, and must be reviewed and confirmed or ' +
  'overridden by an authorized human investigator prior to official action.';

export type SegmentReviewStatus =
  | 'pending_review'
  | 'confirmed'
  | 'corrected'
  | 'overridden'
  | 'dismissed';

export interface AICandidateSegment {
  id: string;
  evidence_id: string;
  start_time_seconds: number;
  end_time_seconds: number;
  raw_score: number;
  calibrated_score?: number | null;
  raw_label: string;
  review_status: SegmentReviewStatus;
  reviewed_by_id?: string | null;
  review_notes?: string | null;
  created_at: string;
}
