import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuditPage } from '../pages/AuditPage';
import { auditApi } from '../api/audit';
import type { SecurityAuditEvent, AuditVerificationReport, AuditEventExportResponse } from '../types/audit';

vi.mock('../api/audit', () => ({
  auditApi: {
    searchEvents: vi.fn(),
    getEventDetail: vi.fn(),
    verifyChain: vi.fn(),
    exportEvents: vi.fn(),
  },
}));

describe('AuditPage Component', () => {
  const sampleEvent: SecurityAuditEvent = {
    id: 'e1111111-1111-1111-1111-111111111111',
    sequence_number: 101,
    action: 'auth:login:success',
    actor_id: 'usr-999',
    actor_role: 'ROLE_INVESTIGATOR',
    target_type: 'incident',
    target_id: 'INC-2026-01',
    outcome: 'success',
    event_hash: 'a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0',
    previous_event_hash: 'prev000000000000000000000000000000000000000000000000000000000000',
    created_at: '2026-10-29T01:00:00Z',
    details: { note: 'Login verified', token: '***REDACTED***' },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(auditApi.searchEvents).mockResolvedValue({
      items: [sampleEvent],
      pagination: {
        page: 1,
        page_size: 50,
        total_items: 1,
        total_pages: 1,
        has_next: false,
        has_prev: false,
      },
    });
  });

  it('renders page header and audit records table', async () => {
    render(
      <MemoryRouter>
        <AuditPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Security Audit & Operational Ledger')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('auth:login:success')).toBeInTheDocument();
    });
    expect(screen.getByText('101')).toBeInTheDocument();
    expect(screen.getByText('INC-2026-01')).toBeInTheDocument();
  });

  it('filters audit records when applying search', async () => {
    render(
      <MemoryRouter>
        <AuditPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('auth:login:success')).toBeInTheDocument();
    });

    const actionInput = screen.getByLabelText(/Audit Action/i);
    fireEvent.change(actionInput, { target: { value: 'incident:submitted' } });

    const applyButton = screen.getByRole('button', { name: /Apply Filters/i });
    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(auditApi.searchEvents).toHaveBeenCalledWith(
        expect.objectContaining({
          action: 'incident:submitted',
        })
      );
    });
  });

  it('opens event detail modal when inspecting an event row', async () => {
    vi.mocked(auditApi.getEventDetail).mockResolvedValueOnce(sampleEvent);

    render(
      <MemoryRouter>
        <AuditPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('auth:login:success')).toBeInTheDocument();
    });

    const inspectBtn = screen.getByTitle('View Full Record');
    fireEvent.click(inspectBtn);

    await waitFor(() => {
      expect(screen.getByText('Audit Record #101')).toBeInTheDocument();
    });

    expect(screen.getByText(/Redacted Structured Action Details/i)).toBeInTheDocument();
    expect(screen.getByText(/SHA-256 Event Record Hash/i)).toBeInTheDocument();
    expect(screen.getAllByText('***REDACTED***', { exact: false }).length).toBeGreaterThan(0);
  });

  it('triggers cryptographic chain verification and renders status card', async () => {
    const mockReport: AuditVerificationReport = {
      status: 'verified',
      chain_valid: true,
      total_events_verified: 101,
      first_sequence_number: 1,
      last_sequence_number: 101,
      tampered_event_ids: [],
      tampered_sequence_numbers: [],
      errors: [],
      disclaimer: 'Cryptographic hash chaining detects historical alteration...',
      verified_at: '2026-10-29T01:15:00Z',
    };
    vi.mocked(auditApi.verifyChain).mockResolvedValueOnce(mockReport);

    render(
      <MemoryRouter>
        <AuditPage />
      </MemoryRouter>
    );

    const verifyBtn = screen.getByRole('button', { name: /Verify Integrity/i });
    fireEvent.click(verifyBtn);

    await waitFor(() => {
      expect(screen.getByText(/Chain Verified \(Valid\)/i)).toBeInTheDocument();
    });

    expect(screen.getAllByText('101').length).toBeGreaterThan(0);
    expect(screen.getByText(/Cryptographic hash chaining detects/i)).toBeInTheDocument();
  });

  it('opens export modal and executes ledger export', async () => {
    const mockExportResponse: AuditEventExportResponse = {
      export_id: 'exp-123',
      exported_at: '2026-10-29T01:20:00Z',
      export_format: 'json',
      total_records: 1,
      content: '[{"id": "1", "action": "auth:login:success"}]',
      hash_digest: 'sha256_mock_digest_value',
    };
    vi.mocked(auditApi.exportEvents).mockResolvedValueOnce(mockExportResponse);

    render(
      <MemoryRouter>
        <AuditPage />
      </MemoryRouter>
    );

    const exportBtn = screen.getByRole('button', { name: /Export Ledger/i });
    fireEvent.click(exportBtn);

    await waitFor(() => {
      expect(screen.getByText('Export Audit Ledger Records')).toBeInTheDocument();
    });

    const submitExportBtn = screen.getByRole('button', { name: /Generate Export Payload/i });
    fireEvent.click(submitExportBtn);

    await waitFor(() => {
      expect(screen.getByText('sha256_mock_digest_value')).toBeInTheDocument();
    });

    expect(screen.getByText(/Download File/i)).toBeInTheDocument();
  });
});
