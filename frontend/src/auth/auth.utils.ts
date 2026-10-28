/**
 * Sanitizes and validates internal redirect paths to prevent open redirect vulnerabilities.
 */
export function sanitizeInternalRedirect(path: unknown): string {
  if (typeof path !== 'string') return '/';
  // Must begin with a single slash and not double slashes (protocol-relative URLs)
  if (path.startsWith('/') && !path.startsWith('//') && !path.includes('\\')) {
    return path;
  }
  return '/';
}
