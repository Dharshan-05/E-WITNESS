/**
 * Standardized API Error and Response Types.
 * Matches backend `backend/app/schemas/common.py` ErrorResponse envelope.
 */

export interface ApiErrorDetail {
  field?: string | null;
  message: string;
  error_type?: string;
}

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    request_id?: string | null;
    details?: ApiErrorDetail[] | null;
  };
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly requestId?: string | null;
  public readonly details?: ApiErrorDetail[] | null;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId?: string | null,
    details?: ApiErrorDetail[] | null
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset?: number;
  next_cursor?: string | null;
  has_more?: boolean;
}

export interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined | null>;
  token?: string | null;
}
