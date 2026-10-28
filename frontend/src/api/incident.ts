import { apiClient } from './client';
import type {
  IncidentCreate,
  IncidentRead,
  IncidentListParams,
  QueueParams,
  ReviewQueueWorkloadSummary,
} from '../types/incident';
import type { PaginatedResponse } from '../types/api';

/**
 * Submit a new incident report bound to the authenticated caller's identity.
 * POST /api/v1/incidents
 */
export async function submitIncident(payload: IncidentCreate): Promise<IncidentRead> {
  return apiClient.post<IncidentRead>('/incidents', payload);
}

/**
 * List incidents visible to the caller (own reports or department scope).
 * GET /api/v1/incidents
 */
export async function listIncidents(
  params?: IncidentListParams
): Promise<PaginatedResponse<IncidentRead>> {
  return apiClient.get<PaginatedResponse<IncidentRead>>('/incidents', {
    params: params as Record<string, string | number | boolean | undefined | null>,
  });
}

/**
 * Retrieve paginated review queue incidents for authorized reviewers.
 * GET /api/v1/incidents/queue
 */
export async function getReviewQueue(
  params?: QueueParams
): Promise<PaginatedResponse<IncidentRead>> {
  return apiClient.get<PaginatedResponse<IncidentRead>>('/incidents/queue', {
    params: params as Record<string, string | number | boolean | undefined | null>,
  });
}

/**
 * Retrieve workload metrics summary for the review queue.
 * GET /api/v1/incidents/queue/workload
 */
export async function getReviewQueueWorkload(
  reviewerId?: string
): Promise<ReviewQueueWorkloadSummary> {
  return apiClient.get<ReviewQueueWorkloadSummary>('/incidents/queue/workload', {
    params: reviewerId ? { reviewer_id: reviewerId } : undefined,
  });
}

/**
 * Retrieve a single incident by its unique ID.
 * GET /api/v1/incidents/{incident_id}
 */
export async function getIncident(incidentId: string): Promise<IncidentRead> {
  return apiClient.get<IncidentRead>(`/incidents/${encodeURIComponent(incidentId)}`);
}
