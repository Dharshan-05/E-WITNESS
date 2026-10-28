/**
 * Campus Incident Types.
 * Matches backend `backend/app/schemas/incident.py` and `backend/app/core/incident.py`.
 */

export type IncidentCategory =
  | 'academic_misconduct'
  | 'harassment_discrimination'
  | 'property_damage_theft'
  | 'safety_hazard'
  | 'physical_assault'
  | 'other';

export type IncidentSeverity = 'low' | 'medium' | 'high' | 'critical';

export type IncidentStatus =
  | 'submitted'
  | 'triaged'
  | 'under_investigation'
  | 'closed'
  | 'dismissed';

export type AssignmentStatus =
  | 'unassigned'
  | 'assigned'
  | 'acknowledged'
  | 'completed';

export interface IncidentRead {
  id: string;
  reference_number: string;
  title: string;
  description: string;
  category: IncidentCategory | string;
  severity: IncidentSeverity | string;
  status: IncidentStatus | string;
  location: string;
  occurred_at: string;
  reporter_id: string;
  department_id: string;
  assigned_reviewer_id?: string | null;
  assignment_status?: AssignmentStatus | string;
  assigned_at?: string | null;
  acknowledged_at?: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Backward compatibility alias for IncidentRead.
 */
export type Incident = IncidentRead;

export interface IncidentCreate {
  title: string;
  description: string;
  category: IncidentCategory;
  severity?: IncidentSeverity;
  location: string;
  occurred_at: string; // ISO 8601 UTC timestamp (must not be in the future)
  department_id?: string | null;
}

export interface IncidentUpdate {
  title?: string;
  description?: string;
  category?: IncidentCategory;
  severity?: IncidentSeverity;
  location?: string;
  occurred_at?: string;
}

export interface ReviewQueueWorkloadSummary {
  pending: number;
  assigned: number;
  unassigned: number;
  overdue: number;
  completed: number;
  total: number;
}

export interface IncidentListParams {
  page?: number;
  page_size?: number;
  status?: string;
  category?: string;
  severity?: string;
  search?: string;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

export interface QueueParams extends IncidentListParams {
  reviewer_id?: string;
  assignment_status?: string;
}

export interface CategoryOption {
  value: IncidentCategory;
  label: string;
  description: string;
  iconName: string;
}

export interface SeverityOption {
  value: IncidentSeverity;
  label: string;
  description: string;
  color: string;
  badgeVariant: 'default' | 'primary' | 'success' | 'warning' | 'danger';
}

export const INCIDENT_CATEGORIES: CategoryOption[] = [
  {
    value: 'academic_misconduct',
    label: 'Academic Misconduct',
    description: 'Cheating, plagiarism, unauthorized materials, or exam disruptions.',
    iconName: 'GraduationCap',
  },
  {
    value: 'harassment_discrimination',
    label: 'Harassment / Discrimination',
    description: 'Targeted harassment, discriminatory conduct, Title IX concerns, or intimidation.',
    iconName: 'UserX',
  },
  {
    value: 'property_damage_theft',
    label: 'Property Damage / Theft',
    description: 'Vandalism, unauthorized equipment access, stolen campus or personal property.',
    iconName: 'Building',
  },
  {
    value: 'safety_hazard',
    label: 'Safety Hazard',
    description: 'Physical danger, blocked fire exits, chemical spills, or unsafe infrastructure.',
    iconName: 'AlertTriangle',
  },
  {
    value: 'physical_assault',
    label: 'Physical Assault',
    description: 'Physical violence, altercation, bodily harm, or imminent threats.',
    iconName: 'ShieldAlert',
  },
  {
    value: 'other',
    label: 'Other Incident',
    description: 'Other institutional policy violations or campus incidents not covered above.',
    iconName: 'FileText',
  },
];

export const INCIDENT_SEVERITIES: SeverityOption[] = [
  {
    value: 'low',
    label: 'Low',
    description: 'Minor infraction, non-urgent concern, or informational report.',
    color: 'text-slate-700 bg-slate-100 border-slate-200',
    badgeVariant: 'default',
  },
  {
    value: 'medium',
    label: 'Medium',
    description: 'Standard misconduct requiring routine departmental review.',
    color: 'text-blue-700 bg-blue-100 border-blue-200',
    badgeVariant: 'primary',
  },
  {
    value: 'high',
    label: 'High',
    description: 'Substantial harm, active disruption, or immediate investigation required.',
    color: 'text-amber-700 bg-amber-100 border-amber-200',
    badgeVariant: 'warning',
  },
  {
    value: 'critical',
    label: 'Critical',
    description: 'Imminent danger, severe violence, or campus-wide safety threat.',
    color: 'text-rose-700 bg-rose-100 border-rose-200',
    badgeVariant: 'danger',
  },
];
