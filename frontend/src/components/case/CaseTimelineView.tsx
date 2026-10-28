import React from 'react';
import {
  Clock,
  Shield,
  CheckCircle2,
  XCircle,
  ArrowRight,
  User,
  Hash,
  Activity,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/EmptyState';
import { Skeleton } from '../ui/Skeleton';
import type { CaseTimelineEventRead } from '../../types/case';

interface CaseTimelineViewProps {
  events: CaseTimelineEventRead[];
  isLoading: boolean;
  hasMore?: boolean;
  onLoadMore?: () => void;
  isLoadingMore?: boolean;
}

/**
 * Distinguish custody-related events from case status/administrative events.
 */
function isCustodyEvent(eventType: string): boolean {
  const normalized = eventType.toLowerCase();
  return (
    normalized.includes('evidence') ||
    normalized.includes('custody') ||
    normalized.includes('hold') ||
    normalized.includes('hash') ||
    normalized.includes('tamper')
  );
}

/**
 * Format event type for human-friendly label.
 */
function formatEventType(eventType: string): string {
  return eventType
    .replace(/^case:/i, '')
    .replace(/^evidence:/i, '')
    .replace(/[:_]/g, ' ')
    .toUpperCase();
}

/**
 * Chronological, accessible Case Activity Timeline & Chain-of-Custody View (Phase 88).
 */
export const CaseTimelineView: React.FC<CaseTimelineViewProps> = ({
  events,
  isLoading,
  hasMore = false,
  onLoadMore,
  isLoadingMore = false,
}) => {
  if (isLoading) {
    return (
      <div className="space-y-4 p-4" data-testid="timeline-loading">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <EmptyState
        icon={<Activity className="h-6 w-6 text-slate-400" />}
        title="No Activity Events Recorded"
        description="There are no recorded activity or chain-of-custody timeline events for this investigation case."
      />
    );
  }

  return (
    <div className="space-y-6" data-testid="case-timeline-view">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Activity className="h-4 w-4 text-indigo-600" />
          <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
            Case Activity & Custody Ledger
          </h3>
          <Badge variant="default" size="sm">
            {events.length} {events.length === 1 ? 'event' : 'events'}
          </Badge>
        </div>
        <span className="text-xs text-slate-500 font-mono">
          Authoritative Server Records
        </span>
      </div>

      {/* Timeline Stream */}
      <ol
        className="relative border-l border-slate-200 ml-3.5 space-y-6"
        aria-label="Case Activity Timeline"
      >
        {events.map((event) => {
          const custody = isCustodyEvent(event.event_type);
          const isSuccess = event.outcome === 'success';
          const isFailure = event.outcome === 'failure' || event.outcome === 'denied';

          return (
            <li
              key={event.id}
              className="ml-6 group"
              data-testid={`timeline-event-${event.id}`}
            >
              {/* Timeline marker node */}
              <span
                className={`absolute -left-3 flex items-center justify-center w-6 h-6 rounded-full ring-4 ring-white ${
                  custody
                    ? 'bg-purple-600 text-white'
                    : isSuccess
                      ? 'bg-indigo-600 text-white'
                      : 'bg-rose-600 text-white'
                }`}
              >
                {custody ? (
                  <Shield className="h-3 w-3" />
                ) : isSuccess ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : isFailure ? (
                  <XCircle className="h-3 w-3" />
                ) : (
                  <Clock className="h-3 w-3" />
                )}
              </span>

              {/* Event Card */}
              <div
                className={`p-4 rounded-lg border bg-white shadow-xs transition-colors hover:border-slate-300 ${
                  custody ? 'border-purple-200 bg-purple-50/20' : 'border-slate-200'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge
                      variant={custody ? 'purple' : 'primary'}
                      size="sm"
                    >
                      {formatEventType(event.event_type)}
                    </Badge>

                    {custody && (
                      <Badge variant="purple" size="sm">
                        CUSTODY
                      </Badge>
                    )}

                    <Badge
                      variant={isSuccess ? 'success' : isFailure ? 'danger' : 'warning'}
                      size="sm"
                    >
                      {event.outcome.toUpperCase()}
                    </Badge>

                    {event.sequence_number !== null && event.sequence_number !== undefined && (
                      <span className="text-[11px] font-mono text-slate-400 flex items-center">
                        <Hash className="h-2.5 w-2.5 mr-0.5" />
                        {event.sequence_number}
                      </span>
                    )}
                  </div>

                  <span className="text-xs text-slate-500 font-medium flex items-center">
                    <Clock className="h-3 w-3 mr-1 text-slate-400" />
                    {new Date(event.timestamp).toLocaleString()}
                  </span>
                </div>

                {/* Event Summary */}
                <p className="text-sm font-semibold text-slate-800 mb-1">
                  {event.summary}
                </p>

                {/* Actor & Reference Details */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 mt-2 pt-2 border-t border-slate-100">
                  {event.actor_role && (
                    <span className="flex items-center">
                      <User className="h-3 w-3 mr-1 text-slate-400" />
                      Role: <strong className="ml-1 text-slate-700">{event.actor_role}</strong>
                    </span>
                  )}

                  {event.actor_id && (
                    <span className="font-mono text-[11px] text-slate-400 truncate max-w-[180px]" title={event.actor_id}>
                      Actor: {event.actor_id.slice(0, 8)}…
                    </span>
                  )}

                  {event.case_reference && (
                    <span className="font-mono text-[11px] text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                      {event.case_reference}
                    </span>
                  )}
                </div>

                {/* Structured event metadata */}
                {event.details && Object.keys(event.details).length > 0 && (
                  <div className="mt-2.5 bg-slate-50 rounded p-2.5 border border-slate-100 text-xs">
                    <span className="font-semibold text-slate-600 block mb-1">
                      Event Attributes:
                    </span>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-[11px] font-mono">
                      {Object.entries(event.details).map(([key, value]) => (
                        <div key={key} className="truncate">
                          <span className="text-slate-500">{key}:</span>{' '}
                          <span className="text-slate-800" title={String(value)}>
                            {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Pagination Load More */}
      {hasMore && (
        <div className="pt-2 flex justify-center">
          <Button
            variant="outline"
            size="sm"
            onClick={onLoadMore}
            isLoading={isLoadingMore}
            rightIcon={<ArrowRight className="h-4 w-4" />}
          >
            Load Older Events
          </Button>
        </div>
      )}
    </div>
  );
};
