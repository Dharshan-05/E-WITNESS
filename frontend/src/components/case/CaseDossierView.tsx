import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  FolderOpen,
  Shield,
  Lock,
  AlertTriangle,
  PlusCircle,
  Paperclip,
  Activity,
  ChevronLeft,
  RefreshCw,
  X,
  FileText,
  Film,
  Play,
  Cpu,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card, CardContent } from '../ui/Card';
import { Alert } from '../ui/Alert';
import { Skeleton } from '../ui/Skeleton';
import { CaseTimelineView } from './CaseTimelineView';
import { VideoEvidenceReviewModal } from '../video/VideoEvidenceReviewModal';
import {
  TransitionStatusModal,
  AssignInvestigatorModal,
  SubmitForReviewModal,
  PlaceLegalHoldModal,
} from './CaseActionDialogs';
import type {
  CaseRead,
  CaseIncidentRead,
  CaseEvidenceItemRead,
  CaseNoteRead,
  CaseTimelineEventRead,
  CaseAISegmentRead,
  CaseStatus,
  CasePriority,
} from '../../types/case';
import {
  getCase,
  listCaseIncidents,
  linkIncident,
  unlinkIncident,
  listCaseEvidence,
  linkEvidence,
  unlinkEvidence,
  listCaseNotes,
  createCaseNote,
  listCaseAISegments,
  getCaseActivityTimeline,
  releaseLegalHold,
} from '../../api/case';

interface CaseDossierViewProps {
  caseId: string;
  onBack?: () => void;
  onCaseUpdated?: (updated: CaseRead) => void;
}

export const CaseDossierView: React.FC<CaseDossierViewProps> = ({
  caseId,
  onBack,
  onCaseUpdated,
}) => {
  const [caseItem, setCaseItem] = useState<CaseRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Active dossier tab: 'overview' | 'incidents' | 'evidence' | 'ai-review' | 'notes' | 'timeline'
  const [activeTab, setActiveTab] = useState<'overview' | 'incidents' | 'evidence' | 'ai-review' | 'notes' | 'timeline'>('overview');

  // Sub-resources
  const [incidents, setIncidents] = useState<CaseIncidentRead[]>([]);
  const [evidence, setEvidence] = useState<CaseEvidenceItemRead[]>([]);
  const [notes, setNotes] = useState<CaseNoteRead[]>([]);
  const [aiSegments, setAiSegments] = useState<CaseAISegmentRead[]>([]);
  const [timelineEvents, setTimelineEvents] = useState<CaseTimelineEventRead[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineHasMore, setTimelineHasMore] = useState(false);
  const [timelineCursor, setTimelineCursor] = useState<string | null>(null);

  // Modals state
  const [showTransitionModal, setShowTransitionModal] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [showSubmitReviewModal, setShowSubmitReviewModal] = useState(false);
  const [showHoldModal, setShowHoldModal] = useState(false);
  const [selectedEvidenceForHold, setSelectedEvidenceForHold] = useState<string | null>(null);
  const [selectedEvidenceForReview, setSelectedEvidenceForReview] = useState<CaseEvidenceItemRead | null>(null);

  // Inline forms state
  const [linkIncidentId, setLinkIncidentId] = useState('');
  const [linkEvidenceId, setLinkEvidenceId] = useState('');
  const [newNoteContent, setNewNoteContent] = useState('');
  const [newNoteVisibility, setNewNoteVisibility] = useState<'internal' | 'confidential' | 'restricted' | 'public'>('internal');
  const [actionError, setActionError] = useState<string | null>(null);

  const onCaseUpdatedRef = useRef(onCaseUpdated);
  useEffect(() => {
    onCaseUpdatedRef.current = onCaseUpdated;
  }, [onCaseUpdated]);

  // Fetch full case dossier
  const fetchCaseDetails = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getCase(caseId);
      setCaseItem(data);

      // Concurrent fetch of relational items
      const [incRes, eviRes, notesRes, aiRes] = await Promise.all([
        listCaseIncidents(caseId).catch(() => []),
        listCaseEvidence(caseId).catch(() => []),
        listCaseNotes(caseId).catch(() => []),
        listCaseAISegments(caseId).catch(() => []),
      ]);

      setIncidents(incRes);
      setEvidence(eviRes);
      setNotes(notesRes);
      setAiSegments(aiRes);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to retrieve case dossier.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  // Fetch timeline events
  const fetchTimeline = useCallback(async (cursor?: string) => {
    setTimelineLoading(true);
    try {
      const res = await getCaseActivityTimeline(caseId, {
        limit: 50,
        cursor,
        ascending: false,
      });

      if (cursor) {
        setTimelineEvents((prev) => [...prev, ...res.items]);
      } else {
        setTimelineEvents(res.items);
      }
      setTimelineHasMore(res.has_more);
      setTimelineCursor(res.next_cursor || null);
    } catch {
      // Timeline failure
    } finally {
      setTimelineLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    fetchCaseDetails();
  }, [fetchCaseDetails]);

  useEffect(() => {
    if (activeTab === 'timeline') {
      fetchTimeline();
    }
  }, [activeTab, fetchTimeline]);

  // Handle Link Incident
  const handleLinkIncident = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionError(null);
    const cleanId = linkIncidentId.trim();
    if (!cleanId) return;

    try {
      const linked = await linkIncident(caseId, { incident_id: cleanId });
      setIncidents((prev) => [...prev, linked]);
      setLinkIncidentId('');
      fetchCaseDetails();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to link incident.');
    }
  };

  // Handle Unlink Incident
  const handleUnlinkIncident = async (incidentId: string) => {
    if (!confirm('Are you sure you want to unlink this incident from the case?')) return;
    try {
      await unlinkIncident(caseId, incidentId);
      setIncidents((prev) => prev.filter((i) => i.incident_id !== incidentId));
      fetchCaseDetails();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to unlink incident.');
    }
  };

  // Handle Link Evidence
  const handleLinkEvidence = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionError(null);
    const cleanId = linkEvidenceId.trim();
    if (!cleanId) return;

    try {
      const linked = await linkEvidence(caseId, { evidence_id: cleanId });
      setEvidence((prev) => [...prev, linked]);
      setLinkEvidenceId('');
      fetchCaseDetails();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to link evidence.');
    }
  };

  // Handle Unlink Evidence
  const handleUnlinkEvidence = async (evidenceId: string) => {
    if (!confirm('Are you sure you want to unlink this evidence item from the case?')) return;
    try {
      await unlinkEvidence(caseId, evidenceId);
      setEvidence((prev) => prev.filter((e) => e.evidence_id !== evidenceId));
      fetchCaseDetails();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to unlink evidence.');
    }
  };

  // Handle Release Legal Hold
  const handleReleaseHold = async (evidenceId: string, holdId: string) => {
    const reason = prompt('Enter mandatory legal hold release reason (min 10 characters):');
    if (!reason || reason.trim().length < 10) {
      alert('Hold release cancelled: minimum 10-character reason is mandatory.');
      return;
    }

    try {
      await releaseLegalHold(caseId, evidenceId, holdId, { release_reason: reason.trim() });
      fetchCaseDetails();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to release legal hold.');
    }
  };

  // Handle Add Note
  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionError(null);
    const cleanContent = newNoteContent.trim();
    if (cleanContent.length < 5) {
      setActionError('Note content must be at least 5 characters.');
      return;
    }

    try {
      const created = await createCaseNote(caseId, {
        content: cleanContent,
        visibility: newNoteVisibility,
      });
      setNotes((prev) => [created, ...prev]);
      setNewNoteContent('');
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to create case note.');
    }
  };

  if (loading) {
    return (
      <div className="space-y-4 p-6 bg-white rounded-xl border border-slate-200" data-testid="dossier-loading">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-4 w-1/2" />
        <div className="grid grid-cols-4 gap-4 pt-4">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
        <Skeleton className="h-48 w-full pt-4" />
      </div>
    );
  }

  if (error || !caseItem) {
    return (
      <Card className="border-rose-200 bg-rose-50/50">
        <CardContent className="p-6 text-center space-y-3">
          <AlertTriangle className="h-8 w-8 text-rose-600 mx-auto" />
          <h2 className="text-base font-bold text-slate-900">Case Dossier Unavailable</h2>
          <p className="text-xs text-rose-700">{error || 'Case record not found or access denied.'}</p>
          <div className="pt-2 flex justify-center gap-2">
            {onBack && (
              <Button variant="outline" size="sm" onClick={onBack}>
                <ChevronLeft className="h-4 w-4 mr-1" />
                Return to Cases
              </Button>
            )}
            <Button variant="primary" size="sm" onClick={fetchCaseDetails}>
              <RefreshCw className="h-4 w-4 mr-1" />
              Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const getStatusBadgeVariant = (status: CaseStatus): 'default' | 'primary' | 'success' | 'warning' | 'danger' => {
    switch (status) {
      case 'open':
      case 'under_investigation':
        return 'primary';
      case 'pending_review':
      case 'pending_supervisor_review':
        return 'warning';
      case 'resolved':
      case 'closed':
        return 'success';
      case 'suspended':
        return 'default';
      case 'reopened':
        return 'danger';
      default:
        return 'default';
    }
  };

  const getPriorityBadgeVariant = (priority: CasePriority): 'default' | 'primary' | 'warning' | 'danger' => {
    switch (priority) {
      case 'critical':
        return 'danger';
      case 'high':
        return 'warning';
      case 'medium':
        return 'primary';
      default:
        return 'default';
    }
  };

  return (
    <div className="space-y-6" data-testid="case-dossier-view">
      {/* Dossier Header */}
      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              {onBack && (
                <Button variant="ghost" size="sm" onClick={onBack} className="p-1 h-auto text-slate-500 mr-1" aria-label="Back to cases">
                  <ChevronLeft className="h-5 w-5" />
                </Button>
              )}
              <span className="font-mono text-xs font-bold text-indigo-700 bg-indigo-50 px-2.5 py-1 rounded border border-indigo-200">
                {caseItem.reference_number}
              </span>
              <Badge variant={getStatusBadgeVariant(caseItem.status)}>
                {caseItem.status.replace(/_/g, ' ').toUpperCase()}
              </Badge>
              <Badge variant={getPriorityBadgeVariant(caseItem.priority)}>
                {caseItem.priority.toUpperCase()}
              </Badge>
              {caseItem.is_legal_hold && (
                <Badge variant="purple" className="flex items-center gap-1">
                  <Lock className="h-3 w-3" />
                  LEGAL HOLD ACTIVE
                </Badge>
              )}
            </div>
            <h1 className="text-xl font-bold text-slate-900 mt-1">{caseItem.title}</h1>
          </div>

          {/* Consequential Action Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowTransitionModal(true)}
            >
              Transition Status
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAssignModal(true)}
            >
              Assign Lead
            </Button>

            {caseItem.status === 'under_investigation' && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setShowSubmitReviewModal(true)}
              >
                Submit for Review
              </Button>
            )}
          </div>
        </div>

        {/* Global Action Error */}
        {actionError && (
          <Alert variant="error">
            <div className="flex items-center justify-between">
              <span>{actionError}</span>
              <button type="button" onClick={() => setActionError(null)} className="text-rose-600 p-0.5">
                <X className="h-4 w-4" />
              </button>
            </div>
          </Alert>
        )}

        {/* Quick Metadata Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs bg-slate-50 p-3.5 rounded-lg border border-slate-100">
          <div>
            <span className="text-slate-400 block font-medium">Department</span>
            <span className="font-semibold text-slate-800">{caseItem.department_name || caseItem.department_id}</span>
          </div>
          <div>
            <span className="text-slate-400 block font-medium">Lead Investigator</span>
            <span className="font-semibold text-slate-800">
              {caseItem.lead_investigator_name || (caseItem.lead_investigator_id ? `${caseItem.lead_investigator_id.slice(0, 8)}…` : 'Unassigned')}
            </span>
          </div>
          <div>
            <span className="text-slate-400 block font-medium">Version</span>
            <span className="font-mono font-semibold text-slate-800">v{caseItem.version_id}</span>
          </div>
          <div>
            <span className="text-slate-400 block font-medium">Created Date</span>
            <span className="font-semibold text-slate-800">{new Date(caseItem.created_at).toLocaleDateString()}</span>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="border-b border-slate-200">
        <nav className="-mb-px flex space-x-6 overflow-x-auto" aria-label="Case Dossier Tabs">
          <button
            type="button"
            onClick={() => setActiveTab('overview')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 whitespace-nowrap ${
              activeTab === 'overview'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <FolderOpen className="h-4 w-4" />
            <span>Overview</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('incidents')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 whitespace-nowrap ${
              activeTab === 'incidents'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <Shield className="h-4 w-4" />
            <span>Linked Incidents ({incidents.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('evidence')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 whitespace-nowrap ${
              activeTab === 'evidence'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <Paperclip className="h-4 w-4" />
            <span>Evidence Inventory ({evidence.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('ai-review')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 whitespace-nowrap ${
              activeTab === 'ai-review'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <Cpu className="h-4 w-4" />
            <span>AI Review & Video ({aiSegments.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('notes')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 whitespace-nowrap ${
              activeTab === 'notes'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <FileText className="h-4 w-4" />
            <span>Case Notes ({notes.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('timeline')}
            className={`py-3 px-1 border-b-2 font-medium text-sm flex items-center space-x-2 whitespace-nowrap ${
              activeTab === 'timeline'
                ? 'border-indigo-600 text-indigo-600 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <Activity className="h-4 w-4" />
            <span>Activity & Custody Ledger</span>
          </button>
        </nav>
      </div>

      {/* Tab Panels */}
      <div>
        {/* OVERVIEW TAB */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6 space-y-4">
                <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                  Factual Case Summary
                </h3>
                <div className="p-4 bg-slate-50 rounded-lg border border-slate-100 text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
                  {caseItem.summary}
                </div>

                {caseItem.legal_hold_reason && (
                  <div className="p-4 bg-purple-50/70 border border-purple-200 rounded-lg text-xs text-purple-900 space-y-1">
                    <span className="font-bold flex items-center gap-1.5">
                      <Lock className="h-3.5 w-3.5 text-purple-600" />
                      Active Legal Hold Justification
                    </span>
                    <p>{caseItem.legal_hold_reason}</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Institutional Statutory Notice */}
            <div className="flex items-start gap-3 p-4 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900">
              <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold block mb-0.5">Authoritative Case Record Notice</span>
                Investigation case dossiers represent official institutional records under university oversight. All status transitions, investigator assignments, evidence links, and legal holds create immutable chain-of-custody audit logs.
              </div>
            </div>
          </div>
        )}

        {/* LINKED INCIDENTS TAB */}
        {activeTab === 'incidents' && (
          <div className="space-y-4">
            {/* Link Incident Form */}
            <form onSubmit={handleLinkIncident} className="p-4 bg-white rounded-xl border border-slate-200 shadow-xs flex flex-col sm:flex-row gap-3">
              <input
                type="text"
                value={linkIncidentId}
                onChange={(e) => setLinkIncidentId(e.target.value)}
                placeholder="Enter Incident UUID to link..."
                className="flex-1 px-3.5 py-2 text-sm rounded-lg border border-slate-300 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              />
              <Button variant="primary" size="sm" type="submit">
                <PlusCircle className="h-4 w-4 mr-1.5" />
                Link Incident
              </Button>
            </form>

            {/* Incidents List */}
            {incidents.length === 0 ? (
              <p className="text-xs text-slate-400 italic p-4 text-center">
                No incidents currently linked to this investigation case.
              </p>
            ) : (
              <div className="space-y-2">
                {incidents.map((inc) => (
                  <Card key={inc.id} className="border-slate-200">
                    <CardContent className="p-4 flex items-center justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                            {inc.incident_reference_number || inc.incident_id.slice(0, 8) + '…'}
                          </span>
                          <Badge variant="primary" size="sm">
                            {inc.link_type.toUpperCase()}
                          </Badge>
                          {inc.incident_status && (
                            <Badge variant="default" size="sm">
                              {inc.incident_status.toUpperCase()}
                            </Badge>
                          )}
                        </div>
                        <p className="text-sm font-semibold text-slate-800">
                          {inc.incident_title || 'Linked Campus Incident'}
                        </p>
                        <span className="text-xs text-slate-400">
                          Linked on {new Date(inc.created_at).toLocaleString()}
                        </span>
                      </div>

                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleUnlinkIncident(inc.incident_id)}
                        className="text-xs text-rose-600 hover:text-rose-800"
                      >
                        Unlink
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* EVIDENCE INVENTORY TAB */}
        {activeTab === 'evidence' && (
          <div className="space-y-4">
            {/* Link Evidence Form */}
            <form onSubmit={handleLinkEvidence} className="p-4 bg-white rounded-xl border border-slate-200 shadow-xs flex flex-col sm:flex-row gap-3">
              <input
                type="text"
                value={linkEvidenceId}
                onChange={(e) => setLinkEvidenceId(e.target.value)}
                placeholder="Enter Evidence Attachment UUID to link..."
                className="flex-1 px-3.5 py-2 text-sm rounded-lg border border-slate-300 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
              />
              <Button variant="primary" size="sm" type="submit">
                <Paperclip className="h-4 w-4 mr-1.5" />
                Link Evidence
              </Button>
            </form>

            {/* Evidence Items List */}
            {evidence.length === 0 ? (
              <p className="text-xs text-slate-400 italic p-4 text-center">
                No evidence attachments linked to this case inventory.
              </p>
            ) : (
              <div className="space-y-2">
                {evidence.map((item) => (
                  <Card key={item.id} className="border-slate-200">
                    <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                      <div className="space-y-1.5 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-sm font-semibold text-slate-900 truncate">
                            {item.file_name}
                          </span>
                          <Badge
                            variant={item.integrity_status === 'verified' ? 'success' : 'danger'}
                            size="sm"
                          >
                            {item.integrity_status.toUpperCase()}
                          </Badge>
                          {item.is_legal_hold && (
                            <Badge variant="purple" size="sm" className="flex items-center gap-1">
                              <Lock className="h-2.5 w-2.5" />
                              HOLD ACTIVE
                            </Badge>
                          )}
                        </div>

                        <div className="text-xs text-slate-500 flex flex-wrap items-center gap-x-4 gap-y-1">
                          <span>{(item.file_size_bytes / (1024 * 1024)).toFixed(2)} MB</span>
                          <span className="font-mono text-slate-400">
                            ID: {item.evidence_id.slice(0, 8)}…
                          </span>
                          <span className="font-mono text-[10px] text-slate-400" title={item.sha256_hash}>
                            SHA-256: {item.sha256_hash.slice(0, 12)}…
                          </span>
                          <span>Events: {item.chain_of_custody_events_count}</span>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-2 shrink-0">
                        {/* Video Review Action */}
                        {(item.content_type.startsWith('video/') ||
                          item.file_name.match(/\.(mp4|webm|mov|avi)$/i)) && (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => setSelectedEvidenceForReview(item)}
                            className="text-xs"
                          >
                            <Play className="h-3.5 w-3.5 mr-1" />
                            Review Video & AI
                          </Button>
                        )}

                        {!item.is_legal_hold ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setSelectedEvidenceForHold(item.evidence_id);
                              setShowHoldModal(true);
                            }}
                            className="text-xs text-purple-700 hover:text-purple-900"
                          >
                            <Lock className="h-3.5 w-3.5 mr-1" />
                            Place Hold
                          </Button>
                        ) : (
                          item.active_hold_ids && item.active_hold_ids[0] && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleReleaseHold(item.evidence_id, item.active_hold_ids[0])}
                              className="text-xs text-amber-700 hover:text-amber-900"
                            >
                              Release Hold
                            </Button>
                          )
                        )}

                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleUnlinkEvidence(item.evidence_id)}
                          disabled={item.is_legal_hold}
                          className="text-xs text-rose-600 hover:text-rose-800 disabled:opacity-40"
                          title={item.is_legal_hold ? 'Cannot unlink evidence under active legal hold' : undefined}
                        >
                          Unlink
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* AI REVIEW & VIDEO TAB */}
        {activeTab === 'ai-review' && (
          <div className="space-y-4">
            {/* Advisory Banner */}
            <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl flex items-start gap-3 text-xs text-amber-900">
              <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <h4 className="font-semibold text-amber-950">
                  Institutional AI Governance & Human Review Policy
                </h4>
                <p className="text-amber-800 leading-relaxed">
                  AI video violence detections and candidate segments are strictly non-authoritative
                  investigative leads. They must never independently establish guilt, identify a
                  suspect, or determine case disposition without authorized human investigator review.
                </p>
              </div>
            </div>

            {/* AI Summary Metrics */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3 bg-white rounded-xl border border-slate-200 text-center">
                <span className="text-xs text-slate-500 block">Total Segments</span>
                <span className="text-lg font-bold text-slate-800">{aiSegments.length}</span>
              </div>
              <div className="p-3 bg-white rounded-xl border border-amber-200 text-center bg-amber-50/30">
                <span className="text-xs text-amber-700 block">Pending Review</span>
                <span className="text-lg font-bold text-amber-700">
                  {aiSegments.filter((s) => s.review_status === 'pending_review').length}
                </span>
              </div>
              <div className="p-3 bg-white rounded-xl border border-emerald-200 text-center bg-emerald-50/30">
                <span className="text-xs text-emerald-700 block">Confirmed</span>
                <span className="text-lg font-bold text-emerald-700">
                  {aiSegments.filter((s) => s.review_status === 'confirmed').length}
                </span>
              </div>
              <div className="p-3 bg-white rounded-xl border border-rose-200 text-center bg-rose-50/30">
                <span className="text-xs text-rose-700 block">Rejected</span>
                <span className="text-lg font-bold text-rose-700">
                  {aiSegments.filter((s) => s.review_status === 'rejected').length}
                </span>
              </div>
            </div>

            {/* Segments List */}
            {aiSegments.length === 0 ? (
              <div className="p-8 text-center bg-white rounded-xl border border-slate-200 text-slate-400 space-y-2">
                <Film className="h-8 w-8 mx-auto text-slate-300" />
                <p className="text-sm font-semibold text-slate-700">No AI Candidate Segments</p>
                <p className="text-xs max-w-sm mx-auto">
                  No automated candidate segments have been linked to this case file. Use the Evidence
                  tab to inspect video evidence.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {aiSegments.map((seg) => {
                  const parentEvidence = evidence.find((e) => e.evidence_id === seg.evidence_id);
                  const mins = Math.floor(seg.start_seconds / 60);
                  const secs = Math.floor(seg.start_seconds % 60);
                  const timeFormatted = `${mins.toString().padStart(2, '0')}:${secs
                    .toString()
                    .padStart(2, '0')}`;

                  return (
                    <Card key={seg.id} className="border-slate-200">
                      <CardContent className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono text-xs font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                              {timeFormatted} ({seg.duration_seconds.toFixed(1)}s)
                            </span>
                            <Badge
                              variant={
                                seg.review_status === 'confirmed'
                                  ? 'success'
                                  : seg.review_status === 'rejected'
                                  ? 'danger'
                                  : seg.review_status === 'inconclusive'
                                  ? 'default'
                                  : 'warning'
                              }
                              size="sm"
                            >
                              {seg.review_status.toUpperCase()}
                            </Badge>
                            {seg.is_override && (
                              <Badge variant="purple" size="sm">
                                OVERRIDE
                              </Badge>
                            )}
                          </div>

                          <p className="text-xs font-semibold text-slate-800">
                            {seg.human_corrected_label || seg.label} —{' '}
                            <span className="text-slate-500 font-normal">
                              Score: {((seg.raw_score ?? seg.score) * 100).toFixed(1)}% (
                              {seg.model_name || 'classifier'})
                            </span>
                          </p>

                          <p className="text-[11px] text-slate-400">
                            Evidence:{' '}
                            <span className="text-slate-600 font-medium">
                              {parentEvidence ? parentEvidence.file_name : seg.evidence_id.slice(0, 8) + '…'}
                            </span>
                          </p>
                        </div>

                        {parentEvidence && (
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => setSelectedEvidenceForReview(parentEvidence)}
                            className="text-xs shrink-0"
                          >
                            <Play className="h-3.5 w-3.5 mr-1" />
                            Open Video Reviewer
                          </Button>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* CASE NOTES TAB */}
        {activeTab === 'notes' && (
          <div className="space-y-4">
            {/* Add Note Form */}
            <form onSubmit={handleAddNote} className="p-4 bg-white rounded-xl border border-slate-200 shadow-xs space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  Author Investigative Note
                </span>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-500 font-medium">Visibility Tier:</span>
                  <select
                    value={newNoteVisibility}
                    onChange={(e) =>
                      setNewNoteVisibility(
                        e.target.value as 'internal' | 'confidential' | 'restricted' | 'public'
                      )
                    }
                    className="px-2 py-1 rounded border border-slate-300 text-xs bg-white"
                  >
                    <option value="internal">Internal (Team)</option>
                    <option value="confidential">Confidential (Supervisors)</option>
                    <option value="restricted">Restricted (Counsel)</option>
                    <option value="public">Public</option>
                  </select>
                </div>
              </div>

              <textarea
                rows={3}
                value={newNoteContent}
                onChange={(e) => setNewNoteContent(e.target.value)}
                placeholder="Record investigative observations, interview statements, or case progress notes..."
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-indigo-100 focus:border-indigo-600"
                required
              />

              <div className="flex justify-end">
                <Button variant="primary" size="sm" type="submit">
                  <PlusCircle className="h-4 w-4 mr-1.5" />
                  Record Case Note
                </Button>
              </div>
            </form>

            {/* Notes List */}
            {notes.length === 0 ? (
              <p className="text-xs text-slate-400 italic p-4 text-center">
                No notes recorded for this investigation case.
              </p>
            ) : (
              <div className="space-y-3">
                {notes.map((note) => (
                  <Card key={note.id} className="border-slate-200">
                    <CardContent className="p-4 space-y-2">
                      <div className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2">
                          <Badge
                            variant={
                              note.visibility === 'restricted'
                                ? 'danger'
                                : note.visibility === 'confidential'
                                  ? 'warning'
                                  : 'default'
                            }
                            size="sm"
                          >
                            {note.visibility.toUpperCase()}
                          </Badge>
                          <span className="font-mono text-slate-400">
                            Author: {note.author_id.slice(0, 8)}…
                          </span>
                          <span className="font-mono text-slate-400">v{note.version_id}</span>
                        </div>
                        <span className="text-slate-400">
                          {new Date(note.created_at).toLocaleString()}
                        </span>
                      </div>

                      <p className="text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
                        {note.content}
                      </p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TIMELINE TAB */}
        {activeTab === 'timeline' && (
          <CaseTimelineView
            events={timelineEvents}
            isLoading={timelineLoading && timelineEvents.length === 0}
            hasMore={timelineHasMore}
            isLoadingMore={timelineLoading}
            onLoadMore={() => fetchTimeline(timelineCursor || undefined)}
          />
        )}
      </div>

      {/* Action Dialogs */}
      {showTransitionModal && (
        <TransitionStatusModal
          caseItem={caseItem}
          isOpen={showTransitionModal}
          onClose={() => setShowTransitionModal(false)}
          onSuccess={(updated) => {
            setCaseItem(updated);
            onCaseUpdated?.(updated);
          }}
        />
      )}

      {showAssignModal && (
        <AssignInvestigatorModal
          caseItem={caseItem}
          isOpen={showAssignModal}
          onClose={() => setShowAssignModal(false)}
          onSuccess={(updated) => {
            setCaseItem(updated);
            onCaseUpdated?.(updated);
          }}
        />
      )}

      {showSubmitReviewModal && (
        <SubmitForReviewModal
          caseItem={caseItem}
          isOpen={showSubmitReviewModal}
          onClose={() => setShowSubmitReviewModal(false)}
          onSuccess={(updated) => {
            setCaseItem(updated);
            onCaseUpdated?.(updated);
          }}
        />
      )}

      {showHoldModal && selectedEvidenceForHold && (
        <PlaceLegalHoldModal
          caseId={caseId}
          evidenceId={selectedEvidenceForHold}
          isOpen={showHoldModal}
          onClose={() => {
            setShowHoldModal(false);
            setSelectedEvidenceForHold(null);
          }}
          onSuccess={() => {
            fetchCaseDetails();
          }}
        />
      )}

      {/* Video Evidence & AI Review Modal */}
      {selectedEvidenceForReview && (
        <VideoEvidenceReviewModal
          caseId={caseId}
          evidenceItem={selectedEvidenceForReview}
          incidentId={incidents[0]?.incident_id}
          isOpen={!!selectedEvidenceForReview}
          onClose={() => setSelectedEvidenceForReview(null)}
          onRefreshCase={fetchCaseDetails}
        />
      )}
    </div>
  );
};
