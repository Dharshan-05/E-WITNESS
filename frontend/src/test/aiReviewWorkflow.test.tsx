import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AISegmentsList } from '../components/video/AISegmentsList';
import { AISegmentReviewModal } from '../components/video/AISegmentReviewModal';
import { AISegmentHistoryModal } from '../components/video/AISegmentHistoryModal';
import { VideoEvidenceReviewModal } from '../components/video/VideoEvidenceReviewModal';
import type {
  CaseAISegmentRead,
  CaseEvidenceItemRead,
  CaseAISegmentHistoryItemRead,
} from '../types/case';
import * as caseApi from '../api/case';
import * as evidenceApi from '../api/evidence';
import * as authModule from '../auth';

describe('AI Review Workflow Components', () => {
  const mockSegment: CaseAISegmentRead = {
    id: 'seg-1',
    case_id: 'case-1',
    segment_id: 's-1',
    linked_by_id: 'user-1',
    investigative_relevance: 'candidate_lead',
    created_at: '2026-10-28T12:00:00Z',
    job_id: 'job-1',
    evidence_id: 'evi-1',
    incident_id: 'inc-1',
    start_seconds: 12.0,
    end_seconds: 18.0,
    duration_seconds: 6.0,
    score: 0.84,
    raw_score: 0.84,
    calibrated_score: 0.79,
    label: 'violence',
    model_name: 'violence-classifier',
    model_version: '1.0.0',
    review_status: 'pending_review',
    decision_revision: 1,
    is_override: false,
    advisory_disclaimer: 'Advisory candidate only.',
  };

  const mockEvidenceItem: CaseEvidenceItemRead = {
    id: 'ce-1',
    case_id: 'case-1',
    evidence_id: 'evi-1',
    linked_by_id: 'user-1',
    is_exhibiting: false,
    created_at: '2026-10-28T10:00:00Z',
    file_name: 'corridor_cam.mp4',
    file_size_bytes: 35000000,
    content_type: 'video/mp4',
    sha256_hash: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
    integrity_status: 'verified',
    evidence_status: 'active',
    is_legal_hold: false,
    chain_of_custody_events_count: 3,
    active_holds_count: 0,
    audit_event_count: 2,
    active_hold_ids: [],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    window.HTMLMediaElement.prototype.play = vi.fn().mockImplementation(() => Promise.resolve());
    window.HTMLMediaElement.prototype.pause = vi.fn();
  });

  describe('AISegmentsList', () => {
    it('renders candidate segment list with advisory banner', () => {
      render(
        <AISegmentsList
          segments={[mockSegment]}
          currentTime={0}
          onSeekTo={vi.fn()}
          onReviewSegment={vi.fn()}
          onViewHistory={vi.fn()}
        />
      );

      expect(screen.getByText(/Non-Authoritative Advisory Leads/i)).toBeInTheDocument();
      expect(screen.getByText(/00:12 – 00:18/i)).toBeInTheDocument();
      expect(screen.getByText(/PENDING REVIEW/i)).toBeInTheDocument();
      expect(screen.getByText(/84.0%/i)).toBeInTheDocument();
    });

    it('renders empty state when no segments exist', () => {
      render(
        <AISegmentsList
          segments={[]}
          currentTime={0}
          onSeekTo={vi.fn()}
          onReviewSegment={vi.fn()}
          onViewHistory={vi.fn()}
        />
      );

      expect(screen.getByText(/No Candidate Segments/i)).toBeInTheDocument();
    });

    it('triggers onSeekTo, onReviewSegment, and onViewHistory callbacks', () => {
      const onSeekMock = vi.fn();
      const onReviewMock = vi.fn();
      const onHistoryMock = vi.fn();

      render(
        <AISegmentsList
          segments={[mockSegment]}
          currentTime={0}
          onSeekTo={onSeekMock}
          onReviewSegment={onReviewMock}
          onViewHistory={onHistoryMock}
        />
      );

      fireEvent.click(screen.getByText(/00:12 – 00:18/i));
      expect(onSeekMock).toHaveBeenCalledWith(12.0);

      fireEvent.click(screen.getByRole('button', { name: /Review Decision/i }));
      expect(onReviewMock).toHaveBeenCalledWith(mockSegment);

      fireEvent.click(screen.getByRole('button', { name: /History/i }));
      expect(onHistoryMock).toHaveBeenCalledWith(mockSegment);
    });
  });

  describe('AISegmentReviewModal', () => {
    it('validates minimum 10-character rationale on submission', async () => {
      const onSubmitMock = vi.fn();

      render(
        <AISegmentReviewModal
          segment={mockSegment}
          isOpen={true}
          onClose={vi.fn()}
          onSubmitReview={onSubmitMock}
        />
      );

      // Verify button is disabled initially (empty rationale)
      const submitBtn = screen.getByRole('button', { name: /Submit Determination/i });
      expect(submitBtn).toBeDisabled();

      // Enter short rationale (< 10 chars)
      const rationaleInput = screen.getByPlaceholderText(/Provide detailed factual justification/i);
      fireEvent.change(rationaleInput, { target: { value: 'Too short' } });
      expect(submitBtn).toBeDisabled();

      // Enter valid rationale (>= 10 chars)
      fireEvent.change(rationaleInput, {
        target: { value: 'Detailed factual justification statement here.' },
      });
      expect(submitBtn).not.toBeDisabled();
    });

    it('submits valid human review determination and closes modal', async () => {
      const onSubmitMock = vi.fn().mockResolvedValue(undefined);
      const onCloseMock = vi.fn();

      render(
        <AISegmentReviewModal
          segment={mockSegment}
          isOpen={true}
          onClose={onCloseMock}
          onSubmitReview={onSubmitMock}
        />
      );

      // Select "Confirm"
      const confirmBtn = screen.getByRole('button', { name: /Confirm/i });
      fireEvent.click(confirmBtn);

      // Enter rationale >= 10 chars
      const rationaleInput = screen.getByPlaceholderText(/Provide detailed factual justification/i);
      fireEvent.change(rationaleInput, {
        target: {
          value: 'Physical struggle observed between two subjects near doorway.',
        },
      });

      const submitBtn = screen.getByRole('button', { name: /Submit Determination/i });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(onSubmitMock).toHaveBeenCalledWith(
          expect.objectContaining({
            review_status: 'confirmed',
            review_rationale: 'Physical struggle observed between two subjects near doorway.',
            expected_review_status: 'pending_review',
            expected_revision: 1,
            is_override: false,
          }),
          undefined
        );
        expect(onCloseMock).toHaveBeenCalled();
      });
    });

    it('supports supervisor override and formal case finding creation', async () => {
      const onSubmitMock = vi.fn().mockResolvedValue(undefined);
      const previouslyReviewedSegment: CaseAISegmentRead = {
        ...mockSegment,
        review_status: 'rejected',
        decision_revision: 2,
      };

      render(
        <AISegmentReviewModal
          segment={previouslyReviewedSegment}
          isOpen={true}
          onClose={vi.fn()}
          onSubmitReview={onSubmitMock}
          isSupervisor={true}
        />
      );

      // Toggle supervisor override
      const overrideCheckbox = screen.getByLabelText(/Apply as Authorized Supervisor Override/i);
      fireEvent.click(overrideCheckbox);

      // Switch to Confirm
      fireEvent.click(screen.getByRole('button', { name: /Confirm/i }));

      // Fill in rationale
      const rationaleInput = screen.getByPlaceholderText(/Provide detailed factual justification/i);
      fireEvent.change(rationaleInput, {
        target: {
          value: 'Supervisor override: re-evaluation confirms violent physical struggle.',
        },
      });

      // Enable formal case finding
      const findingCheckbox = screen.getByLabelText(
        /Record Formal Case Finding for this Segment/i
      );
      fireEvent.click(findingCheckbox);

      const titleInput = screen.getByPlaceholderText(/e\.g\. Corroborated altercations/i);
      fireEvent.change(titleInput, { target: { value: 'Doorway confrontation finding' } });

      const submitBtn = screen.getByRole('button', { name: /Submit Determination/i });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(onSubmitMock).toHaveBeenCalledWith(
          expect.objectContaining({
            review_status: 'confirmed',
            is_override: true,
            expected_review_status: 'rejected',
            expected_revision: 2,
          }),
          expect.objectContaining({
            findingType: 'preliminary',
            title: 'Doorway confrontation finding',
          })
        );
      });
    });
  });

  describe('AISegmentHistoryModal', () => {
    it('fetches and displays decision audit log revisions', async () => {
      const mockHistory: CaseAISegmentHistoryItemRead[] = [
        {
          event_id: 'ev-1',
          timestamp: '2026-10-28T14:30:00Z',
          actor_id: 'actor-uuid-1',
          actor_role: 'ROLE_INVESTIGATOR',
          previous_review_status: 'pending_review',
          new_review_status: 'confirmed',
          review_rationale: 'Initial investigator confirmation.',
          is_override: false,
          decision_revision: 1,
        },
      ];

      vi.spyOn(caseApi, 'getCaseAISegmentReviewHistory').mockResolvedValueOnce(mockHistory);

      render(
        <AISegmentHistoryModal
          caseId="case-1"
          segment={mockSegment}
          isOpen={true}
          onClose={vi.fn()}
        />
      );

      expect(screen.getByText(/Segment Review Decision Audit Log/i)).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByText(/REV 1/i)).toBeInTheDocument();
        expect(screen.getByText(/Initial investigator confirmation/i)).toBeInTheDocument();
      });
    });
  });

  describe('VideoEvidenceReviewModal', () => {
    it('loads video download URL and segments, displaying metadata integrity', async () => {
      vi.spyOn(authModule, 'useAuth').mockReturnValue({
        user: {
          id: 'u-1',
          full_name: 'Investigator One',
          email: 'inv@campus.edu',
          account_status: 'active',
          is_active: true,
          department_id: 'd-1',
          session_id: 'sess-1',
          role: {
            id: 'r-1',
            code: 'ROLE_INVESTIGATOR',
            name: 'Investigator',
            description: 'Lead investigator',
            requires_department_scope: true,
            is_system_role: false,
            created_at: '2026-01-01',
            updated_at: '2026-01-01',
          },
          created_at: '2026-01-01',
          updated_at: '2026-01-01',
        },
        status: 'authenticated',
        role: {
          id: 'r-1',
          code: 'ROLE_INVESTIGATOR',
          name: 'Investigator',
          description: 'Lead investigator',
          requires_department_scope: true,
          is_system_role: false,
          created_at: '2026-01-01',
          updated_at: '2026-01-01',
        },
        roleCode: 'ROLE_INVESTIGATOR',
        department: null,
        sessionId: 'sess-1',
        error: null,
        login: vi.fn(),
        logout: vi.fn(),
        refreshSession: vi.fn(),
        hasRole: vi.fn().mockReturnValue(true),
      });

      vi.spyOn(evidenceApi, 'getAttachmentDownloadUrl').mockResolvedValueOnce({
        download_url: 'https://storage.e-witness.local/signed/corridor.mp4',
        filename: 'corridor_cam.mp4',
        content_type: 'video/mp4',
        file_size_bytes: 35000000,
        expires_at: new Date(Date.now() + 300000).toISOString(),
      });

      vi.spyOn(caseApi, 'listCaseEvidenceAISegments').mockResolvedValueOnce([mockSegment]);

      render(
        <VideoEvidenceReviewModal
          caseId="case-1"
          evidenceItem={mockEvidenceItem}
          incidentId="inc-1"
          isOpen={true}
          onClose={vi.fn()}
        />
      );

      // Verify evidence metadata is displayed
      expect(screen.getByText('corridor_cam.mp4')).toBeInTheDocument();
      expect(screen.getByText(/VERIFIED/i)).toBeInTheDocument();
      expect(screen.getByText(/SHA-256:/i)).toBeInTheDocument();
      expect(screen.getByText(/Custody Events: 3/i)).toBeInTheDocument();

      // Verify segments loaded into sidebar
      await waitFor(() => {
        expect(screen.getByText(/00:12 – 00:18/i)).toBeInTheDocument();
      });
    });
  });
});
