import '@testing-library/jest-dom';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Automatically unmount and cleanup DOM after each test run
afterEach(() => {
  cleanup();
});

// Polyfill and normalize Request in Node 20+ / jsdom for Remix router
if (typeof globalThis.Request !== 'undefined') {
  const OriginalRequest = globalThis.Request;
  class SanitizedRequest extends OriginalRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      if (init && 'signal' in init) {
        // Strip signal to avoid jsdom/Node 24 undici AbortSignal instance mismatch
        const copy = { ...init };
        delete copy.signal;
        super(input, copy);
      } else {
        super(input, init);
      }
    }
  }
  globalThis.Request = SanitizedRequest as typeof OriginalRequest;
  if (typeof window !== 'undefined') {
    window.Request = SanitizedRequest as unknown as typeof window.Request;
  }
}

// Mock window.matchMedia if not available in jsdom
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}
