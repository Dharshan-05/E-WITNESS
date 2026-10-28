import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CasesPage } from '../pages/CasesPage';
import * as caseApi from '../api/case';
import type { CaseRead, PaginatedCasesRead } from '../types/case';

describe('CasesPage Component', () => {
  const mockCases: CaseRead[] = [
    {
      id: '11111111-1111-1111-1111-111111111111',
      reference_number: 'CASE-2026-00001',
      title: 'Lab 204 Security Investigation',
      summary: 'Unauthorized entry detected after hours.',
      status: 'under_investigation',
      priority: 'high',
      department_id: 'dept-01',
      created_by_id: 'user-01',
      lead_investigator_id: 'inv-01',
      version_id: 2,
      is_legal_hold: true,
      legal_hold_reason: 'Active litigation request',
      closed_at: null,
      created_at: '2026-10-28T12:00:00Z',
      updated_at: '2026-10-28T12:30:00Z',
      incidents_count: 1,
      evidence_count: 3,
      ai_segments_count: 0,
      department_name: 'Campus Police',
      lead_investigator_name: 'Detective Morris',
    },
    {
      id: '22222222-2222-2222-2222-222222222222',
      reference_number: 'CASE-2026-00002',
      title: 'Dormitory Disruption Inquiry',
      summary: 'Noise and unauthorized property damage report.',
      status: 'open',
      priority: 'medium',
      department_id: 'dept-01',
      created_by_id: 'user-02',
      lead_investigator_id: null,
      version_id: 1,
      is_legal_hold: false,
      legal_hold_reason: null,
      closed_at: null,
      created_at: '2026-10-28T13:00:00Z',
      updated_at: '2026-10-28T13:00:00Z',
      incidents_count: 2,
      evidence_count: 1,
      ai_segments_count: 0,
      department_name: 'Residence Life',
      lead_investigator_name: null,
    },
  ];

  const mockPaginated: PaginatedCasesRead = {
    items: mockCases,
    total: 2,
    limit: 20,
    offset: 0,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(caseApi, 'listCaseAISegments').mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders case list table with reference numbers, status, and metadata', async () => {
    vi.spyOn(caseApi, 'listCases').mockResolvedValue(mockPaginated);

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Investigation Case Management')).toBeInTheDocument();
    expect(screen.getByTestId('case-search-input')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
      expect(screen.getByText('Lab 204 Security Investigation')).toBeInTheDocument();
      expect(screen.getByText('UNDER INVESTIGATION')).toBeInTheDocument();
      expect(screen.getByText('HIGH')).toBeInTheDocument();
      expect(screen.getByText('CASE-2026-00002')).toBeInTheDocument();
      expect(screen.getByText('Dormitory Disruption Inquiry')).toBeInTheDocument();
    });
  });

  it('filters cases on search input submit', async () => {
    const listSpy = vi.spyOn(caseApi, 'listCases').mockResolvedValue(mockPaginated);

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    const searchInput = screen.getByTestId('case-search-input');
    fireEvent.change(searchInput, { target: { value: 'Lab 204' } });

    const filterButton = screen.getByRole('button', { name: /filter/i });
    fireEvent.click(filterButton);

    await waitFor(() => {
      expect(listSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          search: 'Lab 204',
        })
      );
    });
  });

  it('renders empty state when no cases match', async () => {
    vi.spyOn(caseApi, 'listCases').mockResolvedValue({
      items: [],
      total: 0,
      limit: 20,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('No Investigation Cases Found')).toBeInTheDocument();
    });
  });

  it('displays error and allows retry when fetch fails', async () => {
    vi.spyOn(caseApi, 'listCases')
      .mockRejectedValueOnce(new Error('Network timeout fetching cases'))
      .mockResolvedValueOnce(mockPaginated);

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(/Network timeout fetching cases/i)).toBeInTheDocument();
    });

    const retryButton = screen.getByRole('button', { name: /retry/i });
    fireEvent.click(retryButton);

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });
  });

  it('opens dossier view when clicking a case row and allows returning to list', async () => {
    vi.spyOn(caseApi, 'listCases').mockResolvedValue(mockPaginated);
    vi.spyOn(caseApi, 'getCase').mockResolvedValue(mockCases[0]);
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue([]);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue([]);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue([]);

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('CASE-2026-00001')).toBeInTheDocument();
    });

    // Click on row to open dossier
    const row = screen.getByTestId(`case-row-${mockCases[0].id}`);
    fireEvent.click(row);

    await waitFor(() => {
      expect(screen.getByTestId('case-dossier-view')).toBeInTheDocument();
      expect(screen.getByText('Factual Case Summary')).toBeInTheDocument();
      expect(screen.getByText('Unauthorized entry detected after hours.')).toBeInTheDocument();
      expect(screen.getByText(/Active Legal Hold Justification/i)).toBeInTheDocument();
    });

    // Click back button to return to case table
    const backButton = screen.getByRole('button', { name: /back to cases/i });
    fireEvent.click(backButton);

    await waitFor(() => {
      expect(screen.getByTestId('case-list-table')).toBeInTheDocument();
    });
  });

  it('opens Initiate Case modal and submits new case', async () => {
    vi.spyOn(caseApi, 'listCases').mockResolvedValue(mockPaginated);
    const createSpy = vi.spyOn(caseApi, 'createCase').mockResolvedValue({
      ...mockCases[0],
      id: 'new-case-id',
      reference_number: 'CASE-2026-00099',
      title: 'Newly Initiated Case',
    });
    vi.spyOn(caseApi, 'getCase').mockResolvedValue({
      ...mockCases[0],
      id: 'new-case-id',
      reference_number: 'CASE-2026-00099',
      title: 'Newly Initiated Case',
    });
    vi.spyOn(caseApi, 'listCaseIncidents').mockResolvedValue([]);
    vi.spyOn(caseApi, 'listCaseEvidence').mockResolvedValue([]);
    vi.spyOn(caseApi, 'listCaseNotes').mockResolvedValue([]);

    render(
      <MemoryRouter>
        <CasesPage />
      </MemoryRouter>
    );

    const initiateBtn = screen.getByRole('button', { name: /initiate case/i });
    fireEvent.click(initiateBtn);

    expect(screen.getByText('Initiate New Investigation Case')).toBeInTheDocument();

    const titleInput = screen.getByLabelText(/case title/i);
    const summaryInput = screen.getByLabelText(/factual case summary/i);

    fireEvent.change(titleInput, { target: { value: 'Newly Initiated Case' } });
    fireEvent.change(summaryInput, { target: { value: 'Detailed factual narrative for newly initiated case.' } });

    const submitBtn = screen.getByRole('button', { name: /create case file/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Newly Initiated Case',
          summary: 'Detailed factual narrative for newly initiated case.',
        })
      );
    });
  });
});
