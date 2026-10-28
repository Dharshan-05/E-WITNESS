import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VideoPlayer } from '../components/video/VideoPlayer';
import type { CaseAISegmentRead } from '../types/case';

describe('VideoPlayer Component', () => {
  const defaultProps = {
    src: 'https://storage.e-witness.local/signed/evidence-video.mp4',
    filename: 'hallway_camera_01.mp4',
    contentType: 'video/mp4',
    isLoadingUrl: false,
    urlExpiresAt: new Date(Date.now() + 300000).toISOString(),
    onRefreshUrl: vi.fn(),
  };

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
      start_seconds: 5.0,
      end_seconds: 15.0,
      duration_seconds: 10.0,
      score: 0.85,
      label: 'violence',
      review_status: 'pending_review',
      decision_revision: 1,
      is_override: false,
      advisory_disclaimer: 'Advisory candidate only.',
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    // HTMLMediaElement mock methods in jsdom
    window.HTMLMediaElement.prototype.play = vi.fn().mockImplementation(() => Promise.resolve());
    window.HTMLMediaElement.prototype.pause = vi.fn();
  });

  it('renders video element and player controls', () => {
    render(<VideoPlayer {...defaultProps} />);

    expect(screen.getByRole('region', { name: /Video Evidence Player/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Play video/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Skip backward 5 seconds/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Skip forward 5 seconds/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Video scrubber slider/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Playback speed/i)).toBeInTheDocument();
  });

  it('displays loading overlay when requesting streaming URL', () => {
    render(<VideoPlayer {...defaultProps} src={null} isLoadingUrl={true} />);

    expect(screen.getByText(/Requesting authorized streaming URL/i)).toBeInTheDocument();
  });

  it('displays expired URL overlay and provides refresh button', () => {
    const expiredTimestamp = new Date(Date.now() - 10000).toISOString();
    const onRefreshMock = vi.fn();

    render(
      <VideoPlayer
        {...defaultProps}
        urlExpiresAt={expiredTimestamp}
        onRefreshUrl={onRefreshMock}
      />
    );

    expect(screen.getByText(/Presigned Access URL Expired/i)).toBeInTheDocument();
    const refreshBtn = screen.getByRole('button', { name: /Refresh Access Token/i });
    fireEvent.click(refreshBtn);
    expect(onRefreshMock).toHaveBeenCalledTimes(1);
  });

  it('renders non-video format fallback banner when evidence is not a video', () => {
    render(
      <VideoPlayer
        {...defaultProps}
        filename="incident_memo.pdf"
        contentType="application/pdf"
      />
    );

    expect(screen.getByText(/Non-Video Evidence File/i)).toBeInTheDocument();
    expect(screen.getByText(/application\/pdf/i)).toBeInTheDocument();
  });

  it('toggles playback when play/pause button is clicked', () => {
    render(<VideoPlayer {...defaultProps} />);

    const playBtn = screen.getByLabelText(/Play video/i);
    fireEvent.click(playBtn);
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it('changes playback speed when selector changes', () => {
    render(<VideoPlayer {...defaultProps} />);

    const speedSelect = screen.getByLabelText(/Playback speed/i);
    fireEvent.change(speedSelect, { target: { value: '1.5' } });
    expect((speedSelect as HTMLSelectElement).value).toBe('1.5');
  });

  it('toggles mute when volume mute button is clicked', () => {
    render(<VideoPlayer {...defaultProps} />);

    const muteBtn = screen.getByLabelText(/Mute/i);
    fireEvent.click(muteBtn);
    expect(screen.getByLabelText(/Unmute/i)).toBeInTheDocument();
  });

  it('renders candidate segment track markers across duration', () => {
    const onSelectMock = vi.fn();

    const { container } = render(
      <VideoPlayer
        {...defaultProps}
        segments={mockSegments}
        onSelectSegment={onSelectMock}
      />
    );

    // Simulate video loadedmetadata to establish duration
    const video = container.querySelector('video');
    if (video) {
      Object.defineProperty(video, 'duration', { value: 60, writable: true });
      fireEvent.loadedMetadata(video);
    }

    // Segment marker button should exist
    const marker = screen.getByTitle(/AI Segment \[00:05 - 00:15\]/i);
    expect(marker).toBeInTheDocument();

    fireEvent.click(marker);
    expect(onSelectMock).toHaveBeenCalledWith(mockSegments[0]);
  });

  it('handles keyboard shortcuts for accessible player navigation', () => {
    render(<VideoPlayer {...defaultProps} />);

    const playerRegion = screen.getByRole('region', { name: /Video Evidence Player/i });

    // Space key to toggle play
    fireEvent.keyDown(playerRegion, { key: ' ' });
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();

    // Mute key
    fireEvent.keyDown(playerRegion, { key: 'm' });
    expect(screen.getByLabelText(/Unmute/i)).toBeInTheDocument();
  });
});
