/**
 * Session storage adapter for refresh credentials.
 *
 * Security Design:
 * - Access tokens are NEVER persisted to browser storage; they remain strictly in-memory.
 * - Refresh tokens are stored in `sessionStorage` (scoped to the active browser tab/session,
 *   automatically purged when tab/window closes).
 * - Implements in-memory fallback if sessionStorage is blocked by browser privacy policies.
 */

const REFRESH_TOKEN_KEY = 'ewitness_session_rt';

let inMemoryFallbackRefreshToken: string | null = null;

function isSessionStorageAvailable(): boolean {
  try {
    if (typeof window === 'undefined' || !window.sessionStorage) {
      return false;
    }
    const testKey = '__ew_test__';
    window.sessionStorage.setItem(testKey, '1');
    window.sessionStorage.removeItem(testKey);
    return true;
  } catch {
    return false;
  }
}

export const authStorage = {
  getRefreshToken(): string | null {
    if (isSessionStorageAvailable()) {
      return window.sessionStorage.getItem(REFRESH_TOKEN_KEY);
    }
    return inMemoryFallbackRefreshToken;
  },

  setRefreshToken(token: string): void {
    if (isSessionStorageAvailable()) {
      window.sessionStorage.setItem(REFRESH_TOKEN_KEY, token);
    } else {
      inMemoryFallbackRefreshToken = token;
    }
  },

  clear(): void {
    if (isSessionStorageAvailable()) {
      window.sessionStorage.removeItem(REFRESH_TOKEN_KEY);
    }
    inMemoryFallbackRefreshToken = null;
  },
};
