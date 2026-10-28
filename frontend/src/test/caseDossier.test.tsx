import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CaseDossierView } from '../components/case/CaseDossierView';
import * as caseApi from '../api/case';
import type {
  CaseRead,
  CaseIncidentRead,
  CaseEvidenceItemRead,
  CaseNoteRead,
  CaseTimelineResponse,
  CaseAISegmentRead,
} from '../types/case';

describe('CaseDossierView Component', () => {
  const caseId = '11111111-1111-1111-1111-111111111111';

  const mockCase: CaseRead = {
    id: caseId,
    reference_number: 'CASE-2026-00001',
    title: 'North Annex Investigation',
    summary: 'Detailed investigation into unauthorized entry in room 204.',
    status: 'under_investigation',
    priority: 'high',
    department_id: 'dept-01',
    created_by_id: 'user-01',
    lead_investigator_id: 'inv-01',
    version_id: 2,
    is_legal_hold: true,
    legal_hold_reason: 'Court order #2026-099',
    closed_at: null,
    created_at: '2026-10-28T12:00:00Z',
    updated_at: '2026-10-28T12:30:00Z',
    incidents_count: 1,
    evidence_count: 1,
    ai_segments_count: 0,
    department_name: 'Campus Police',
    lead_investigator_name: 'Detective Morris',
  };

  const mockIncidents: CaseIncidentRead[] = [
    {
      id: 'inc-link-01',
      case_id: caseId,
      incident_id: 'inc-01',
      linked_by_id: 'user-01',
      link_type: 'primary',
      created_at: '2026-10-28T12:00:00Z',
      incident_title: 'Lab 204 Alarm Trigger',
      incident_reference_number: 'INC-2026-00045',
      incident_status: 'under_investigation',
    },
  ];

  const mockEvidence: CaseEvidenceItemRead[] = [
    {
      id: 'evi-link-01',
      case_id: caseId,
      evidence_id: 'evi-01',
      linked_by_id: 'user-01',
      is_exhibiting: true,
      created_at: '2026-10-28T12:00:00Z',
      file_name: 'hallway_cctv.mp4',
      file_size_bytes: 20971520,
      content_type: 'video/mp4',
      sha256_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      integrity_status: 'verified',
      is_legal_hold: true,
      chain_of_custody_events_count: 4,
      evidence_status: 'attached',
      active_hold_ids: ['hold-01'],
      active_holds_count: 1,
      audit_event_count: 2,
    },
  ];

  const mockNotes: CaseNoteRead[] = [
    {
      id: 'note-01',
      case_id: caseId,
      author_id: 'user-01',
      visibility: 'confidential',
      content: 'Interviewed night watch staff; log books reviewed.',
      version_id: 1,
      is_archived: false,
      evidence_reference_ids: [],
      created_at: '2026-10-28T12:15:00Z',
      updated_at: '2026-10-28T12:15:00Z',
    },
  ];

  const mockTimeline: CaseTimelineResponse = {
    items: [
      {
        id: 'evt-01',
        case_id: caseId,
        case_reference: 'CASE-2026-00001',
        event_type: 'case:evidence:linked',
        timestamp: '2026-10-28T12:10:00Z',
        sequence_number: 1,
        actor_id: 'user-01',
        actor_role: 'lead_investigator',
        outcome: 'success',
        summary: 'Linked evidence attachment hallway_cctv.mp4',
        details: { evidence_id: 'evi-01', file_name: 'hallway_cctv.mp4' },
      },
      {
        id: 'evt-02',
        case_id: caseId,
        case_reference: 'CASE-2026-00001',
        event_type: 'case:status:transition',
        timestamp: '2026-10-28T12:05:00Z',
        sequence_number: 2,
        actor_id: 'user-01',
        actor_role: 'supervisor',
        outcome: 'success',
        summary: 'Case transition to under_investigation',
        details: { from_status: 'open', to_status: 'under_investigation' },
      },
    ],
    total_count: 2,
    next_cursor: null,
    has_more: false,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(caseApi, 'listCaseAISegments').mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders dossier header, summary, and metadata attributes', async () => {
    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue(mockIncidents);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue(mockEvidence);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue(mockNotes);

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
      expect(screen.getByText('North Annex Investigation')).toBeInTheDocument();
      expect(screen.getByText('UNDER INVESTIGATION')).toBeInTheDocument();
      expect(screen.getByText('HIGH')).toBeInTheDocument();
      expect(screen.getByText('LEGAL HOLD ACTIVE')).toBeInTheDocument();
      expect(screen.getByText(/Detailed investigation into unauthorized entry/i)).toBeInTheDocument();
      expect(screen.getByText(/Court order #2026-099/i)).toBeInTheDocument();
    });
  });

  it('navigates to Linked Incidents tab and links an incident', async () => {
    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue(mockIncidents);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue(mockEvidence);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue(mockNotes);

    const linkSpy = vi.spyOn(caseApi, 'linkIncident').mockResolvedValue({
      id: 'inc-link-02',
      case_id: caseId,
      incident_id: 'inc-02',
      linked_by_id: 'user-01',
      link_type: 'related',
      created_at: '2026-10-28T12:20:00Z',
      incident_title: 'Second Incident',
    });

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    const incidentsTab = screen.getByRole('button', { name: /linked incidents/i });
    fireEvent.click(incidentsTab);

    expect(screen.getByText('INC-2026-00045')).toBeInTheDocument();
    expect(screen.getByText('Lab 204 Alarm Trigger')).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/enter incident uuid to link/i);
    fireEvent.change(input, { target: { value: 'inc-02' } });

    const submitBtn = screen.getByRole('button', { name: /link incident/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(linkSpy).toHaveBeenCalledWith(caseId, { incident_id: 'inc-02' });
    });
  });

  it('navigates to Evidence Inventory tab and renders SHA-256 and hold status', async () => {
    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue(mockIncidents);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue(mockEvidence);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue(mockNotes);

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    const evidenceTab = screen.getByRole('button', { name: /evidence inventory/i });
    fireEvent.click(evidenceTab);

    expect(screen.getByText('hallway_cctv.mp4')).toBeInTheDocument();
    expect(screen.getByText('VERIFIED')).toBeInTheDocument();
    expect(screen.getByText('HOLD ACTIVE')).toBeInTheDocument();
    expect(screen.getByText(/20.00 MB/i)).toBeInTheDocument();
    expect(screen.getByText(/SHA-256: e3b0c44298fc…/i)).toBeInTheDocument();
  });

  it('navigates to Case Notes tab and creates an internal note', async () => {
    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue(mockIncidents);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue(mockEvidence);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue(mockNotes);

    const noteSpy = vi.spyOn(caseApi, 'createCaseNote').mockResolvedValue({
      id: 'note-02',
      case_id: caseId,
      author_id: 'user-01',
      visibility: 'internal',
      content: 'New forensic lab observations recorded.',
      version_id: 1,
      is_archived: false,
      evidence_reference_ids: [],
      created_at: '2026-10-28T12:40:00Z',
      updated_at: '2026-10-28T12:40:00Z',
    });

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    const notesTab = screen.getByRole('button', { name: /case notes/i });
    fireEvent.click(notesTab);

    expect(screen.getByText('CONFIDENTIAL')).toBeInTheDocument();
    expect(screen.getByText('Interviewed night watch staff; log books reviewed.')).toBeInTheDocument();

    const noteInput = screen.getByPlaceholderText(/record investigative observations/i);
    fireEvent.change(noteInput, { target: { value: 'New forensic lab observations recorded.' } });

    const submitNoteBtn = screen.getByRole('button', { name: /record case note/i });
    fireEvent.click(submitNoteBtn);

    await waitFor(() => {
      expect(noteSpy).toHaveBeenCalledWith(
        caseId,
        expect.objectContaining({
          content: 'New forensic lab observations recorded.',
          visibility: 'internal',
        })
      );
    });
  });

  it('navigates to Timeline tab and renders chronological events with custody distinction', async () => {
    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue(mockIncidents);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue(mockEvidence);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue(mockNotes);
    vi.spyOn(caseApi, 'getCaseActivityTimeline').mockResolvedValue(mockTimeline);

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    const timelineTab = screen.getByRole('button', { name: /activity & custody ledger/i });
    fireEvent.click(timelineTab);

    await waitFor(() => {
      expect(screen.getByTestId('case-timeline-view')).toBeInTheDocument();
      expect(screen.getByText('Linked evidence attachment hallway_cctv.mp4')).toBeInTheDocument();
      expect(screen.getByText('Case transition to under_investigation')).toBeInTheDocument();
      // Verifies CUSTODY badge is rendered for evidence-linked event
      expect(screen.getByText('CUSTODY')).toBeInTheDocument();
    });
  });

  it('opens Transition Status modal and transitions case lifecycle', async () => {
    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue(mockIncidents);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue(mockEvidence);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue(mockNotes);

    const transitionSpy = vi.spyOn(caseApi, 'transitionCaseStatus').mockResolvedValue({
      ...mockCase,
      status: 'resolved',
      version_id: 3,
    });

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    const transitionBtn = screen.getByRole('button', { name: /transition status/i });
    fireEvent.click(transitionBtn);

    expect(screen.getByRole('heading', { name: /transition case status/i })).toBeInTheDocument();

    const reasonInput = screen.getByPlaceholderText(/state the factual basis/i);
    fireEvent.change(reasonInput, { target: { value: 'Case resolved following comprehensive admissions and evidence match.' } });

    const confirmBtn = screen.getByRole('button', { name: /confirm transition/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(transitionSpy).toHaveBeenCalledWith(
        caseId,
        expect.objectContaining({
          reason: 'Case resolved following comprehensive admissions and evidence match.',
          expected_version_id: 2,
        })
      );
    });
  });

  it('switches to AI Review & Video tab and displays advisory banner and candidate segments', async () => {
    const mockAISegment: CaseAISegmentRead = {
      id: 'seg-link-01',
      case_id: caseId,
      segment_id: 'seg-01',
      linked_by_id: 'user-01',
      investigative_relevance: 'candidate_lead',
      created_at: '2026-10-28T12:00:00Z',
      job_id: 'job-01',
      evidence_id: 'evi-01',
      incident_id: 'inc-01',
      start_seconds: 14.0,
      end_seconds: 22.0,
      duration_seconds: 8.0,
      score: 0.89,
      raw_score: 0.89,
      label: 'violence',
      model_name: 'violence-classifier',
      model_version: '1.0.0',
      review_status: 'pending_review',
      decision_revision: 1,
      is_override: false,
      advisory_disclaimer: 'Advisory candidate only.',
    };

    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCase);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue(mockIncidents);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue(mockEvidence);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue(mockNotes);
    vi.spyOn(caseApi, 'listCaseAISegments').mockResolvedValue([mockAISegment]);

    render(<CaseDossierView caseId={caseId} />);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    const aiTab = screen.getByRole('button', { name: /ai review & video/i });
    fireEvent.click(aiTab);

    // Verifies Institutional AI Governance Policy banner
    expect(screen.getByText(/Institutional AI Governance & Human Review Policy/i)).toBeInTheDocument();
    expect(screen.getByText(/violence —/i)).toBeInTheDocument();
    expect(screen.getByText(/89.0%/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /open video reviewer/i })).toBeInTheDocument();
  });
});
