/**
 * Auth helpers for the Shermos CMS (JWT Bearer + CSRF cookie).
 */

const ACCESS_TOKEN_KEY = "shermos.access_token";

/** Reads the JWT access token from localStorage. */
export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

/** Writes or clears the JWT access token in localStorage. */
export function setAccessToken(token: string | null): void {
  if (token === null) {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
  } else {
    localStorage.setItem(ACCESS_TOKEN_KEY, token);
  }
}

/**
 * Reads the CSRF token from the `csrf_token` cookie.
 * Note: the cookie is set with samesite="none", secure=true — it is only
 * accessible over HTTPS. Returns null in dev over plain HTTP.
 */
export function getCsrfToken(): string | null {
  const match = document.cookie
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith("csrf_token="));
  return match ? decodeURIComponent(match.slice("csrf_token=".length)) : null;
}

/** Clears all CMS auth state (localStorage token; cookie can only be cleared best-effort). */
export function clearAuth(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  // Best-effort: clear the csrf_token cookie (only works if not HttpOnly)
  document.cookie = "csrf_token=; Max-Age=0; path=/; SameSite=None; Secure";
}

/**
 * Returns the Authorization header for outgoing API requests.
 * Returns an empty object if no token is stored yet.
 */
export function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
