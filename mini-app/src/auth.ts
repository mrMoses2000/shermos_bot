/**
 * Auth-mode detection and token helpers.
 *
 * Two modes:
 *   "telegram" — Telegram Mini App (X-Telegram-Init-Data header)
 *   "cms"      — Standalone browser CMS (JWT Bearer + CSRF cookie)
 */

const ACCESS_TOKEN_KEY = "shermos.access_token";

export type AuthMode = "telegram" | "cms";

/** Returns the current auth mode based on Telegram WebApp presence. */
export function detectAuthMode(): AuthMode {
  const initData = window.Telegram?.WebApp?.initData;
  return initData ? "telegram" : "cms";
}

/** Returns Telegram initData string if available, otherwise null. */
export function getInitData(): string | null {
  return window.Telegram?.WebApp?.initData || null;
}

/** Reads the JWT access token from localStorage (CMS mode). */
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
 * Returns the appropriate auth headers for outgoing API requests.
 *
 * Telegram mode → { "X-Telegram-Init-Data": "<initData>" }
 * CMS mode      → { "Authorization": "Bearer <token>" }  (or {} if no token yet)
 */
export function getAuthHeaders(): Record<string, string> {
  const mode = detectAuthMode();
  if (mode === "telegram") {
    const initData = getInitData();
    return initData ? { "X-Telegram-Init-Data": initData } : {};
  }
  // CMS mode
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
