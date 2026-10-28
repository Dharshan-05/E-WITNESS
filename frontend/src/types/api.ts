/**
 * Standardized API Error and Response Types.
 * Matches backend `backend/app/schemas/common.py` ErrorResponse envelope
 * and `backend/app/schemas/pagination.py` PaginatedResponse envelope.
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

export interface PaginationMetadata {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  pagination?: PaginationMetadata;
  total?: number;
  limit?: number;
  offset?: number;
  next_cursor?: string | null;
  has_more?: boolean;
}

export interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined | null>;
  token?: string | null;
}
