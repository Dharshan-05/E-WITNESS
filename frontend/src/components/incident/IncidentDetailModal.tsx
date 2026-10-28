import React, { useEffect, useRef, useState, useCallback } from 'react';
import { X, Calendar, MapPin, Tag, Shield, Clock, AlertTriangle, Paperclip, ChevronDown, ChevronUp } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card, CardContent } from '../ui/Card';
import type { IncidentRead } from '../../types/incident';
import type { EvidenceAttachmentRead } from '../../types/evidence';
import { listAttachments } from '../../api/evidence';
import { EvidenceUploader, EvidenceAttachmentList } from '../evidence';

interface IncidentDetailModalProps {
  incident: IncidentRead | null;
  isOpen: boolean;
  onClose: () => void;
}

export const IncidentDetailModal: React.FC<IncidentDetailModalProps> = ({
  incident,
  isOpen,
  onClose,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const [attachments, setAttachments] = useState<EvidenceAttachmentRead[]>([]);
  const [loadingAttachments, setLoadingAttachments] = useState(false);
  const [showUploader, setShowUploader] = useState(false);

  const fetchAttachments = useCallback(async (incidentId: string) => {
    setLoadingAttachments(true);
    try {
      const items = await listAttachments(incidentId);
      setAttachments(items);
    } catch {
      // Non-fatal if evidence fetch fails or no attachments exist
      setAttachments([]);
    } finally {
      setLoadingAttachments(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen && incident?.id) {
      fetchAttachments(incident.id);
      setShowUploader(false);
    } else {
      setAttachments([]);
      setShowUploader(false);
    }
  }, [isOpen, incident?.id, fetchAttachments]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !incident) return null;

  const getSeverityBadgeVariant = (sev: string): 'default' | 'primary' | 'warning' | 'danger' => {
    switch (sev?.toLowerCase()) {
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

  const getStatusBadgeVariant = (status: string): 'default' | 'primary' | 'success' | 'warning' | 'danger' => {
    switch (status?.toLowerCase()) {
      case 'submitted':
        return 'primary';
      case 'triaged':
        return 'warning';
      case 'under_investigation':
        return 'danger';
      case 'closed':
        return 'success';
      case 'dismissed':
        return 'default';
      default:
        return 'default';
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="incident-modal-title"
    >
      <div
        ref={modalRef}
        className="relative w-full max-w-2xl bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden transform transition-all animate-in fade-in zoom-in-95 duration-150"
      >
        {/* Header */}
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-start justify-between">
          <div className="space-y-1 pr-4">
            <div className="flex items-center space-x-2">
              <span className="font-mono text-xs font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200">
                {incident.reference_number}
              </span>
              <Badge variant={getStatusBadgeVariant(incident.status)} size="sm">
                {incident.status.toUpperCase()}
              </Badge>
              <Badge variant={getSeverityBadgeVariant(incident.severity)} size="sm">
                {incident.severity.toUpperCase()}
              </Badge>
            </div>
            <h2 id="incident-modal-title" className="text-lg font-bold text-slate-900 line-clamp-2">
              {incident.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 p-1 rounded-lg hover:bg-slate-200/60 transition-colors"
            aria-label="Close dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-5 max-h-[70vh] overflow-y-auto">
          {/* Metadata Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs bg-slate-50/70 p-3.5 rounded-lg border border-slate-100">
            <div>
              <span className="text-slate-400 block mb-0.5 font-medium flex items-center space-x-1">
                <Tag className="h-3 w-3" />
                <span>Category</span>
              </span>
              <span className="font-semibold text-slate-800 capitalize">
                {incident.category.replace(/_/g, ' ')}
              </span>
            </div>

            <div>
              <span className="text-slate-400 block mb-0.5 font-medium flex items-center space-x-1">
                <MapPin className="h-3 w-3" />
                <span>Location</span>
              </span>
              <span className="font-semibold text-slate-800 truncate block">{incident.location}</span>
            </div>

            <div>
              <span className="text-slate-400 block mb-0.5 font-medium flex items-center space-x-1">
                <Calendar className="h-3 w-3" />
                <span>Occurred At</span>
              </span>
              <span className="font-semibold text-slate-800">
                {new Date(incident.occurred_at).toLocaleString()}
              </span>
            </div>

            <div>
              <span className="text-slate-400 block mb-0.5 font-medium flex items-center space-x-1">
                <Clock className="h-3 w-3" />
                <span>Reported At</span>
              </span>
              <span className="font-semibold text-slate-800">
                {new Date(incident.created_at).toLocaleString()}
              </span>
            </div>

            <div>
              <span className="text-slate-400 block mb-0.5 font-medium flex items-center space-x-1">
                <Shield className="h-3 w-3" />
                <span>Assignment</span>
              </span>
              <span className="font-semibold text-slate-800 capitalize">
                {incident.assignment_status || 'Unassigned'}
              </span>
            </div>

            <div>
              <span className="text-slate-400 block mb-0.5 font-medium">Department ID</span>
              <span className="font-mono text-slate-600 text-[11px] truncate block">
                {incident.department_id}
              </span>
            </div>
          </div>

          {/* Narrative Statement */}
          <div>
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">
              Factual Narrative Statement
            </h3>
            <div className="p-4 bg-white border border-slate-200 rounded-lg text-sm text-slate-800 whitespace-pre-wrap leading-relaxed">
              {incident.description}
            </div>
          </div>

          {/* Digital Evidence Attachments & Uploader */}
          <div className="space-y-3 pt-2 border-t border-slate-100">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center space-x-1.5">
                <Paperclip className="h-3.5 w-3.5" />
                <span>Evidence Custody ({attachments.length})</span>
              </h3>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowUploader((prev) => !prev)}
                className="text-xs text-indigo-600 hover:text-indigo-800"
                aria-expanded={showUploader}
              >
                {showUploader ? (
                  <>
                    <ChevronUp className="h-3.5 w-3.5 mr-1" />
                    Hide Uploader
                  </>
                ) : (
                  <>
                    <ChevronDown className="h-3.5 w-3.5 mr-1" />
                    Attach New Evidence
                  </>
                )}
              </Button>
            </div>

            {loadingAttachments ? (
              <p className="text-xs text-slate-400 italic">Loading evidence records…</p>
            ) : attachments.length > 0 ? (
              <EvidenceAttachmentList attachments={attachments} />
            ) : (
              <p className="text-xs text-slate-400 italic">No evidence files currently attached to this incident.</p>
            )}

            {showUploader && (
              <div className="mt-3 p-4 bg-slate-50/70 border border-slate-200 rounded-lg">
                <EvidenceUploader
                  incidentId={incident.id}
                  onAttachmentsChange={(newAttachments) => {
                    setAttachments((prev) => [...prev, ...newAttachments]);
                  }}
                />
              </div>
            )}
          </div>

          {/* Institutional Statutory Notice */}
          <Card className="bg-amber-50/50 border-amber-200/80">
            <CardContent className="p-3 text-xs text-amber-900 flex items-start space-x-2.5">
              <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold block mb-0.5">Advisory Workflow Notice</span>
                Incident reports and algorithmic annotations are non-authoritative candidate findings. Formal disciplinary or legal escalations require human investigator confirmation and authorized administrative review.
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-200 flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
};
