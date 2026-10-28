/**
 * Campus Incident Types.
 * Matches backend `backend/app/schemas/incident.py`.
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
  | 'under_review'
  | 'escalated'
  | 'closed'
  | 'archived';

export interface Incident {
  id: string;
  reference_number: string;
  title: string;
  description: string;
  category: IncidentCategory;
  severity: IncidentSeverity;
  status: IncidentStatus;
  location?: string | null;
  occurred_at: string;
  department_id: string;
  reporter_id: string;
  is_anonymous: boolean;
  created_at: string;
  updated_at: string;
}
