import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PlusCircle } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { Button } from '../components/ui/Button';
import { StatutoryNotice } from '../components/ui/StatutoryNotice';
import { CaseListTable, CaseCreateModal, CaseDossierView } from '../components/case';
import { listCases } from '../api/case';
import type { CaseRead, CaseListParams } from '../types/case';

export const CasesPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedCaseIdFromUrl = searchParams.get('caseId');

  const [cases, setCases] = useState<CaseRead[]>([]);
  const [total, setTotal] = useState(0);
  const [limit] = useState(20);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Active filters
  const [filters, setFilters] = useState<CaseListParams>({
    limit: 20,
    offset: 0,
    sort_by: 'created_at',
    sort_order: 'desc',
  });

  // Selected case for dossier inspection
  const [selectedCase, setSelectedCase] = useState<CaseRead | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Fetch case list
  const fetchCases = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await listCases(filters);
      setCases(res.items);
      setTotal(res.total);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to retrieve investigation cases.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchCases();
  }, [fetchCases]);

  // Handle URL caseId parameter sync
  useEffect(() => {
    if (selectedCaseIdFromUrl) {
      const found = cases.find((c) => c.id === selectedCaseIdFromUrl);
      if (found) {
        setSelectedCase(found);
      }
    }
  }, [selectedCaseIdFromUrl, cases]);

  const handleSelectCase = (caseItem: CaseRead) => {
    setSelectedCase(caseItem);
    setSearchParams({ caseId: caseItem.id });
  };

  const handleBackToList = () => {
    setSelectedCase(null);
    setSearchParams({});
    fetchCases();
  };

  const handleCaseUpdated = useCallback((updated: CaseRead) => {
    setSelectedCase(updated);
    setCases((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }, []);

  const handleFilterChange = (newFilters: Partial<CaseListParams>) => {
    setFilters((prev) => ({
      ...prev,
      ...newFilters,
    }));
    if (newFilters.offset !== undefined) {
      setOffset(newFilters.offset);
    }
  };

  return (
    <div className="space-y-6" data-testid="cases-page">
      {/* Statutory Legal & Algorithmic Notice Banner */}
      <StatutoryNotice />

      {/* Page Header */}
      <PageHeader
        title={selectedCase ? `Case Dossier — ${selectedCase.reference_number}` : 'Investigation Case Management'}
        subtitle={
          selectedCase
            ? 'Department-isolated case dossier, relational linkages, evidence chain-of-custody, and supervisory approvals.'
            : 'Authoritative case lifecycle records, active investigator assignments, and evidentiary holds.'
        }
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Cases' },
          ...(selectedCase ? [{ label: selectedCase.reference_number }] : []),
        ]}
        actions={
          !selectedCase ? (
            <Button
              variant="primary"
              size="sm"
              leftIcon={<PlusCircle className="h-4 w-4" />}
              onClick={() => setShowCreateModal(true)}
            >
              Initiate Case
            </Button>
          ) : undefined
        }
      />

      {/* Main View: Dossier or Table */}
      {selectedCase ? (
        <CaseDossierView
          caseId={selectedCase.id}
          onBack={handleBackToList}
          onCaseUpdated={handleCaseUpdated}
        />
      ) : (
        <CaseListTable
          cases={cases}
          total={total}
          limit={limit}
          offset={offset}
          isLoading={isLoading}
          error={error}
          onRefresh={fetchCases}
          onSelectCase={handleSelectCase}
          onFilterChange={handleFilterChange}
        />
      )}

      {/* Create Case Modal */}
      {showCreateModal && (
        <CaseCreateModal
          isOpen={showCreateModal}
          onClose={() => setShowCreateModal(false)}
          onSuccess={(newCase) => {
            fetchCases();
            handleSelectCase(newCase);
          }}
        />
      )}
    </div>
  );
};
