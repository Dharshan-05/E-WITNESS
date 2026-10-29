import React, { useState, useEffect, useCallback } from 'react';
import { PlusCircle, Inbox, ListFilter } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { Button } from '../components/ui/Button';
import { StatutoryNotice } from '../components/ui/StatutoryNotice';
import { Alert } from '../components/ui/Alert';
import { useAuth } from '../auth';
import {
  IncidentIntakeWizard,
  ReviewQueueWorkloadCards,
  ReviewQueueTable,
  MyIncidentsList,
} from '../components/incident';
import { StudentProfileCard, StudentQuickComplaint } from '../components/student';
import { getReviewQueueWorkload } from '../api/incident';
import type { ReviewQueueWorkloadSummary } from '../types/incident';

export const IncidentsPage: React.FC = () => {
  const { hasRole } = useAuth();

  const isReviewer = hasRole([
    'ROLE_INVESTIGATOR',
    'ROLE_DEPT_ADMIN',
    'ROLE_SUPER_ADMIN',
    'investigator',
    'department_admin',
    'super_admin',
  ]);

  // Tab State: 'queue' | 'intake' | 'my-reports'
  const [activeTab, setActiveTab] = useState<'queue' | 'intake' | 'my-reports'>(
    isReviewer ? 'queue' : 'intake'
  );
  const [useDetailedForm, setUseDetailedForm] = useState(false);

  // Workload Summary (for Reviewers)
  const [workload, setWorkload] = useState<ReviewQueueWorkloadSummary | null>(null);
  const [workloadLoading, setWorkloadLoading] = useState(false);
  const [workloadError, setWorkloadError] = useState<string | null>(null);

  const fetchWorkload = useCallback(async () => {
    if (!isReviewer) return;
    setWorkloadLoading(true);
    setWorkloadError(null);
    try {
      const summary = await getReviewQueueWorkload();
      setWorkload(summary);
    } catch {
      // Workload fetch failure is non-fatal; table handles queue loading
      setWorkloadError('Could not refresh workload summary metrics.');
    } finally {
      setWorkloadLoading(false);
    }
  }, [isReviewer]);

  useEffect(() => {
    if (isReviewer && activeTab === 'queue') {
      fetchWorkload();
    }
  }, [isReviewer, activeTab, fetchWorkload]);

  return (
    <div className="space-y-6">
      {/* Statutory Legal & Algorithmic Notice Banner */}
      <StatutoryNotice />

      {/* Page Header */}
      <PageHeader
        title="Incident Intake & Triage Workspace"
        subtitle={
          isReviewer
            ? 'Department-isolated triage queue, workload distribution, and structured incident reporting.'
            : 'Submit and track verified campus incident reports bound to your institutional credentials.'
        }
        breadcrumbs={[
          { label: 'Dashboard', href: '/' },
          { label: 'Incidents' },
        ]}
        actions={
          activeTab !== 'intake' ? (
            <Button
              variant="primary"
              size="sm"
              leftIcon={<PlusCircle className="h-4 w-4" />}
              onClick={() => setActiveTab('intake')}
            >
              Report Incident
            </Button>
          ) : undefined
        }
      />

      {/* Student Profile & Digital Attestation Card */}
      {!isReviewer && (
        <StudentProfileCard
          onReportIncident={() => setActiveTab('intake')}
          onViewMySubmissions={() => setActiveTab('my-reports')}
        />
      )}

      {/* Reviewer Workload Summary (Shown when reviewer is on queue tab) */}
      {isReviewer && activeTab === 'queue' && (
        <div className="space-y-3">
          {workloadError && (
            <Alert variant="warning" title="Workload Notice">
              {workloadError}
            </Alert>
          )}
          <ReviewQueueWorkloadCards summary={workload} isLoading={workloadLoading} />
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="border-b border-slate-200">
        <nav className="-mb-px flex space-x-6" aria-label="Incident Management Views">
          {isReviewer && (
            <button
              type="button"
              onClick={() => setActiveTab('queue')}
              className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
                activeTab === 'queue'
                  ? 'border-indigo-600 text-indigo-600 font-semibold'
                  : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
              }`}
            >
              <Inbox className="h-4 w-4" />
              <span>Department Triage Queue</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => setActiveTab('intake')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
              activeTab === 'intake'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            }`}
          >
            <PlusCircle className="h-4 w-4" />
            <span>Report Incident</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('my-reports')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 transition-colors ${
              activeTab === 'my-reports'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
            }`}
          >
            <ListFilter className="h-4 w-4" />
            <span>My Submissions</span>
          </button>
        </nav>
      </div>

      {/* Tab Panels */}
      <div>
        {activeTab === 'queue' && isReviewer && <ReviewQueueTable />}

        {activeTab === 'intake' && !isReviewer && !useDetailedForm && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setUseDetailedForm(true)}
                className="text-xs text-indigo-600 hover:text-indigo-800 font-medium underline"
              >
                Need multi-category classification? Switch to Detailed Form
              </button>
            </div>
            <StudentQuickComplaint
              onViewMySubmissions={() => setActiveTab('my-reports')}
            />
          </div>
        )}

        {activeTab === 'intake' && (isReviewer || useDetailedForm) && (
          <div className="space-y-3">
            {!isReviewer && (
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setUseDetailedForm(false)}
                  className="text-xs text-indigo-600 hover:text-indigo-800 font-medium underline"
                >
                  ← Switch back to 1-Step Quick Complaint
                </button>
              </div>
            )}
            <IncidentIntakeWizard
              onSuccess={() => {
                if (isReviewer) {
                  fetchWorkload();
                }
              }}
              onViewMyReports={() => setActiveTab('my-reports')}
            />
          </div>
        )}

        {activeTab === 'my-reports' && (
          <MyIncidentsList onReportNew={() => setActiveTab('intake')} />
        )}
      </div>
    </div>
  );
};
