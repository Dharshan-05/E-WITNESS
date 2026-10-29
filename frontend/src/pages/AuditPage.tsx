import React, { useState, useEffect, useCallback } from 'react';
import { PageHeader } from '../components/layout/PageHeader';
import { Alert } from '../components/ui/Alert';
import { AuditFilterToolbar } from '../components/audit/AuditFilterToolbar';
import { AuditEventsTable } from '../components/audit/AuditEventsTable';
import { AuditEventDetailModal } from '../components/audit/AuditEventDetailModal';
import { AuditChainVerificationCard } from '../components/audit/AuditChainVerificationCard';
import { AuditExportModal } from '../components/audit/AuditExportModal';
import { auditApi } from '../api/audit';
import type {
  SecurityAuditEvent,
  AuditSearchFilterParams,
  AuditVerificationReport,
  AuditEventExportResponse,
} from '../types/audit';

export const AuditPage: React.FC = () => {
  const [events, setEvents] = useState<SecurityAuditEvent[]>([]);
  const [totalItems, setTotalItems] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize] = useState<number>(50);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [filters, setFilters] = useState<AuditSearchFilterParams>({});
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Modal & Verification state
  const [selectedEvent, setSelectedEvent] = useState<SecurityAuditEvent | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState<boolean>(false);
  const [_isDetailLoading, setIsDetailLoading] = useState<boolean>(false);

  const [verificationReport, setVerificationReport] = useState<AuditVerificationReport | null>(null);
  const [isVerifying, setIsVerifying] = useState<boolean>(false);
  const [showVerificationCard, setShowVerificationCard] = useState<boolean>(false);

  const [isExportModalOpen, setIsExportModalOpen] = useState<boolean>(false);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [exportResult, setExportResult] = useState<AuditEventExportResponse | null>(null);

  const fetchEvents = useCallback(async (params: AuditSearchFilterParams = {}, page: number = 1) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await auditApi.searchEvents({
        ...params,
        page,
        page_size: pageSize,
      });
      setEvents(response.items);
      if (response.pagination) {
        setTotalItems(response.pagination.total_items);
        setCurrentPage(response.pagination.page);
        setTotalPages(response.pagination.total_pages);
      } else {
        setTotalItems(response.items.length);
        setTotalPages(1);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to retrieve security audit ledger records.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [pageSize]);

  useEffect(() => {
    fetchEvents(filters, currentPage);
  }, [fetchEvents, filters, currentPage]);

  const handleApplyFilters = (newFilters: AuditSearchFilterParams) => {
    setFilters(newFilters);
    setCurrentPage(1);
  };

  const handleResetFilters = () => {
    setFilters({});
    setCurrentPage(1);
  };

  const handlePageChange = (newPage: number) => {
    setCurrentPage(newPage);
  };

  const handleSelectEvent = async (event: SecurityAuditEvent) => {
    setIsDetailLoading(true);
    setSelectedEvent(event);
    setIsDetailModalOpen(true);
    try {
      const detail = await auditApi.getEventDetail(event.id);
      setSelectedEvent(detail);
    } catch {
      // Retain the item from table if single detail lookup fails
    } finally {
      setIsDetailLoading(false);
    }
  };

  const handleVerifyChain = async () => {
    setShowVerificationCard(true);
    setIsVerifying(true);
    try {
      const report = await auditApi.verifyChain(1, 1000);
      setVerificationReport(report);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ledger verification failed.';
      setError(msg);
    } finally {
      setIsVerifying(false);
    }
  };

  const handleExecuteExport = async (format: 'json' | 'csv', limit: number) => {
    setIsExporting(true);
    try {
      const result = await auditApi.exportEvents({
        ...filters,
        export_format: format,
        limit,
      });
      setExportResult(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to export audit ledger.';
      setError(msg);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security Audit & Operational Ledger"
        subtitle="Append-only cryptographic event ledger, sequential hash chain verification, and authorized export."
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Audit Trail' },
        ]}
      />

      {error && (
        <Alert variant="error" title="Audit System Notice">
          {error}
        </Alert>
      )}

      {showVerificationCard && (
        <AuditChainVerificationCard
          report={verificationReport}
          isVerifying={isVerifying}
          onVerify={handleVerifyChain}
          onClose={() => setShowVerificationCard(false)}
        />
      )}

      <AuditFilterToolbar
        filters={filters}
        onApplyFilters={handleApplyFilters}
        onResetFilters={handleResetFilters}
        onOpenVerify={() => {
          setShowVerificationCard(true);
          if (!verificationReport) handleVerifyChain();
        }}
        onOpenExport={() => {
          setExportResult(null);
          setIsExportModalOpen(true);
        }}
        isLoading={isLoading}
      />

      <AuditEventsTable
        events={events}
        totalItems={totalItems}
        currentPage={currentPage}
        pageSize={pageSize}
        totalPages={totalPages}
        isLoading={isLoading}
        onSelectEvent={handleSelectEvent}
        onPageChange={handlePageChange}
      />

      {/* Event Details Modal */}
      <AuditEventDetailModal
        event={selectedEvent}
        isOpen={isDetailModalOpen}
        onClose={() => {
          setIsDetailModalOpen(false);
          setSelectedEvent(null);
        }}
      />

      {/* Export Modal */}
      <AuditExportModal
        isOpen={isExportModalOpen}
        isExporting={isExporting}
        exportResult={exportResult}
        onClose={() => setIsExportModalOpen(false)}
        onExecuteExport={handleExecuteExport}
      />
    </div>
  );
};
