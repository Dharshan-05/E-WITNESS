import { ApiError, type ApiErrorPayload, type RequestOptions } from '../types/api';

/**
 * Token storage and provider protocol for client authentication state.
 */
let authTokenGetter: (() => string | null) | null = null;

export function setAuthTokenGetter(getter: () => string | null): void {
  authTokenGetter = getter;
}

/**
 * Generate a cryptographically random or high-entropy request correlation ID.
 */
export function generateCorrelationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'req-' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
}

/**
 * Centralized, typed HTTP client for E-WITNESS backend services.
 */
export class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl?: string) {
    // Default to Vite environment variable or fall back to /api/v1 proxy path
    const envBase = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_BASE_URL) as string | undefined;
    this.baseUrl = (baseUrl || envBase || '/api/v1').replace(/\/+$/, '');
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  private buildUrl(path: string, params?: RequestOptions['params']): string {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const url = `${this.baseUrl}${cleanPath}`;

    if (!params) return url;

    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        query.append(key, String(value));
      }
    }

    const queryString = query.toString();
    return queryString ? `${url}?${queryString}` : url;
  }

  private resolveHeaders(options?: RequestOptions): Headers {
    const headers = new Headers(options?.headers);

    if (!headers.has('Accept')) {
      headers.set('Accept', 'application/json');
    }

    if (!headers.has('X-Request-ID')) {
      headers.set('X-Request-ID', generateCorrelationId());
    }

    // Resolve bearer auth token
    const token = options?.token ?? (authTokenGetter ? authTokenGetter() : null);
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    return headers;
  }

  public async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const url = this.buildUrl(path, options.params);
    const headers = this.resolveHeaders(options);

    let body = options.body;
    if (body && typeof body === 'object' && !(body instanceof FormData) && !(body instanceof Blob)) {
      body = JSON.stringify(body);
      if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }
    }

    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers,
        body,
      });
    } catch (networkError: unknown) {
      const msg = networkError instanceof Error ? networkError.message : 'Network request failed';
      throw new ApiError(
        0,
        'NETWORK_ERROR',
        `Unable to connect to the E-WITNESS server: ${msg}`,
        headers.get('X-Request-ID')
      );
    }

    // 204 No Content
    if (response.status === 204) {
      return {} as T;
    }

    const contentType = response.headers.get('content-type') || '';
    const isJson = contentType.includes('application/json');

    if (!response.ok) {
      let code = `HTTP_${response.status}`;
      let message = response.statusText || 'Request failed';
      let details = null;
      let requestId = headers.get('X-Request-ID');

      if (isJson) {
        try {
          const errorPayload = (await response.json()) as ApiErrorPayload;
          if (errorPayload?.error) {
            code = errorPayload.error.code || code;
            message = errorPayload.error.message || message;
            requestId = errorPayload.error.request_id || requestId;
            details = errorPayload.error.details || null;
          }
        } catch {
          // Keep default status text
        }
      } else {
        try {
          const text = await response.text();
          if (text) message = text;
        } catch {
          // Keep default
        }
      }

      throw new ApiError(response.status, code, message, requestId, details);
    }

    if (isJson) {
      return (await response.json()) as T;
    }

    return (await response.text()) as unknown as T;
  }

  public get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: 'GET' });
  }

  public post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: 'POST',
      body: body as BodyInit,
    });
  }

  public put<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: 'PUT',
      body: body as BodyInit,
    });
  }

  public patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: 'PATCH',
      body: body as BodyInit,
    });
  }

  public delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>(path, { ...options, method: 'DELETE' });
  }
}

/**
 * Singleton default API client instance configured for app-wide use.
 */
export const apiClient = new ApiClient();
