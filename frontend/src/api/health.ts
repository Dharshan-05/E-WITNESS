import { apiClient } from './client';

export interface HealthStatusResponse {
  status: string;
  app_name?: string;
  version?: string;
  environment?: string;
  timestamp?: string;
  components?: Record<string, boolean | string>;
}

export interface ReadinessResponse {
  status: string;
  checks?: {
    database?: string;
    storage?: string;
    redis?: string;
    [key: string]: unknown;
  };
  timestamp?: string;
}

export const healthApi = {
  checkLiveness(): Promise<HealthStatusResponse> {
    return apiClient.get<HealthStatusResponse>('/health/live');
  },

  checkReadiness(): Promise<ReadinessResponse> {
    return apiClient.get<ReadinessResponse>('/health/ready');
  },
};
