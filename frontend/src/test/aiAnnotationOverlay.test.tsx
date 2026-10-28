import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AIAnnotationOverlay } from '../components/video/AIAnnotationOverlay';
import type { CaseAISegmentRead } from '../types/case';

describe('AIAnnotationOverlay Component', () => {
  const mockSegments: CaseAISegmentRead[] = [
    {
      id: 'seg-1',
      case_id: 'case-1',
      segment_id: 's-1',
      linked_by_id: 'user-1',
      investigative_relevance: 'candidate_lead',
      created_at: '2026-10-28T12:00:00Z',
      job_id: 'job-1',
      evidence_id: 'evi-1',
      incident_id: 'inc-1',
      start_seconds: 10.0,
      end_seconds: 20.0,
      duration_seconds: 10.0,
      score: 0.875,
      raw_score: 0.875,
      calibrated_score: 0.812,
      label: 'violence',
      model_name: 'violence-classifier',
      model_version: '1.0.0',
      review_status: 'pending_review',
      decision_revision: 1,
      is_override: false,
      advisory_disclaimer: 'Advisory candidate only.',
      original_ai_prediction: {
        bbox: [0.1, 0.2, 0.5, 0.6],
      },
    },
  ];

  it('renders nothing when playback time is outside segment bounds', () => {
    const { container } = render(
      <AIAnnotationOverlay
        currentTime={5.0}
        segments={mockSegments}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('renders active AI candidate segment when current time is within bounds', () => {
    render(
      <AIAnnotationOverlay
        currentTime={14.2}
        segments={mockSegments}
      />
    );

    expect(screen.getByText(/AI Candidate Segment \(Advisory\)/i)).toBeInTheDocument();
    expect(screen.getByText(/00:10 – 00:20/i)).toBeInTheDocument();
    expect(screen.getByText(/Status: pending_review/i)).toBeInTheDocument();
    expect(screen.getAllByText(/87.5%/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Calibrated:/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Probabilistic advisory finding. Does not determine guilt or liability/i)
    ).toBeInTheDocument();
  });

  it('calls onSelectSegment when inspect button is clicked', () => {
    const onSelectMock = vi.fn();

    render(
      <AIAnnotationOverlay
        currentTime={15.0}
        segments={mockSegments}
        onSelectSegment={onSelectMock}
      />
    );

    const inspectBtn = screen.getByText(/Inspect \/ Review Decision →/i);
    fireEvent.click(inspectBtn);

    expect(onSelectMock).toHaveBeenCalledWith(mockSegments[0]);
  });

  it('renders spatial bounding box overlay when bbox coordinates are present in metadata', () => {
    const { container } = render(
      <AIAnnotationOverlay
        currentTime={12.0}
        segments={mockSegments}
      />
    );

    // Should find bounding box element with inline percentage styles
    const bboxEl = container.querySelector('div[style*="top: 10%"][style*="left: 20%"]');
    expect(bboxEl).toBeInTheDocument();
  });
});
