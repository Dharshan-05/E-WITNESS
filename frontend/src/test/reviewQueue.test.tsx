import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReviewQueueWorkloadCards } from '../components/incident/ReviewQueueWorkloadCards';
import { ReviewQueueTable } from '../components/incident/ReviewQueueTable';
import * as incidentApi from '../api/incident';
import type { IncidentRead, ReviewQueueWorkloadSummary } from '../types/incident';

describe('Review Queue Components', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('ReviewQueueWorkloadCards', () => {
    it('renders workload summary counters accurately', () => {
      const summary: ReviewQueueWorkloadSummary = {
        pending: 7,
        assigned: 4,
        unassigned: 3,
        overdue: 2,
        completed: 18,
        total: 25,
      };

      render(<ReviewQueueWorkloadCards summary={summary} />);

      expect(screen.getByText('Pending Triage')).toBeInTheDocument();
      expect(screen.getByText('7')).toBeInTheDocument();
      expect(screen.getByText('Unassigned')).toBeInTheDocument();
      expect(screen.getByText('3')).toBeInTheDocument();
      expect(screen.getByText('Assigned')).toBeInTheDocument();
      expect(screen.getByText('4')).toBeInTheDocument();
      expect(screen.getByText('Overdue Reviews')).toBeInTheDocument();
      expect(screen.getByText('2')).toBeInTheDocument();
      expect(screen.getByText('Completed')).toBeInTheDocument();
      expect(screen.getByText('18')).toBeInTheDocument();
      expect(screen.getByText('Total Queue')).toBeInTheDocument();
      expect(screen.getByText('25')).toBeInTheDocument();
    });
  });

  describe('ReviewQueueTable', () => {
    const mockIncidents: IncidentRead[] = [
      {
        id: 'inc-001',
        reference_number: 'INC-2026-AAAA1111',
        title: 'Unauthorized drone observed over sports complex',
        description: 'Commercial quadcopter flying within 50 feet of crowded athletics pavilion.',
        category: 'safety_hazard',
        severity: 'high',
        status: 'submitted',
        location: 'Athletics Pavilion West Field',
        occurred_at: '2026-10-15T14:00:00Z',
        reporter_id: 'usr-reporter-1',
        department_id: 'dept-safety-01',
        assignment_status: 'unassigned',
        created_at: '2026-10-15T14:30:00Z',
        updated_at: '2026-10-15T14:30:00Z',
      },
      {
        id: 'inc-002',
        reference_number: 'INC-2026-BBBB2222',
        title: 'Graffiti tagging on library stone masonry',
        description: 'Aerosol spray paint vandalism found on south exterior facade.',
        category: 'property_damage_theft',
        severity: 'medium',
        status: 'triaged',
        location: 'Central Library South Entrance',
        occurred_at: '2026-10-14T22:00:00Z',
        reporter_id: 'usr-reporter-2',
        department_id: 'dept-facilities-01',
        assignment_status: 'assigned',
        assigned_reviewer_id: 'usr-investigator-1',
        created_at: '2026-10-15T08:00:00Z',
        updated_at: '2026-10-15T09:00:00Z',
      },
    ];

    it('renders queue table rows and opens inspect modal with incident details', async () => {
      const user = userEvent.setup();

      vi.spyOn(incidentApi, 'getReviewQueue').mockResolvedValue({
        items: mockIncidents,
        pagination: {
          page: 1,
          page_size: 15,
          total_items: 2,
          total_pages: 1,
          has_next: false,
          has_prev: false,
        },
      });

      render(<ReviewQueueTable />);

      // Wait for table to load
      await waitFor(() => {
        expect(screen.getByText('INC-2026-AAAA1111')).toBeInTheDocument();
        expect(screen.getByText('INC-2026-BBBB2222')).toBeInTheDocument();
      });

      expect(screen.getByText('Unauthorized drone observed over sports complex')).toBeInTheDocument();
      expect(screen.getByText('Graffiti tagging on library stone masonry')).toBeInTheDocument();

      // Click Inspect on the first row
      const inspectButtons = screen.getAllByRole('button', { name: /Inspect/i });
      await user.click(inspectButtons[0]);

      // Check modal open
      await waitFor(() => {
        const dialog = screen.getByRole('dialog');
        expect(dialog).toBeInTheDocument();
        expect(within(dialog).getByText('Commercial quadcopter flying within 50 feet of crowded athletics pavilion.')).toBeInTheDocument();
        expect(within(dialog).getByText('Athletics Pavilion West Field')).toBeInTheDocument();
        expect(within(dialog).getByText('Advisory Workflow Notice')).toBeInTheDocument();
      });

      // Close modal
      const closeButton = screen.getByRole('button', { name: /Close dialog/i });
      await user.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });

    it('renders empty state when queue returns zero matching incidents', async () => {
      vi.spyOn(incidentApi, 'getReviewQueue').mockResolvedValue({
        items: [],
        pagination: {
          page: 1,
          page_size: 15,
          total_items: 0,
          total_pages: 0,
          has_next: false,
          has_prev: false,
        },
      });

      render(<ReviewQueueTable />);

      await waitFor(() => {
        expect(screen.getByText('No Incidents Match Queue Filters')).toBeInTheDocument();
      });
    });
  });
});
