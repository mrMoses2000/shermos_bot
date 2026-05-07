/**
 * API client for the Shermos CMS.
 *
 * Supports two auth modes:
 *   CMS JWT           — pass auth: { jwt: true } to use global auth helpers (auth.ts)
 *   CMS admin token   — pass auth: { adminToken: string } for token-based access
 *
 * In CMS JWT mode a 401 triggers one silent token-refresh attempt before
 * redirecting the user to /login.
 */

import {
  getAccessToken,
  getCsrfToken,
  getAuthHeaders,
  setAccessToken,
} from "../auth";

// Configurable API base URL for separate-deploy mode.
// Empty string => same-origin (dev mode).
// Absolute URL  => Netlify-deployed frontend hitting an external API.
const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

/** Unified auth discriminator. */
export type ApiAuth = { jwt: true } | { adminToken?: string };

// ─── internal helpers ────────────────────────────────────────────────────────

function resolveAuthHeaders(auth: ApiAuth): Record<string, string> {
  if ("jwt" in auth && auth.jwt) {
    // CMS / global-auth path
    return getAuthHeaders();
  }
  // Admin token path
  const obj = auth as { adminToken?: string };
  if (obj.adminToken) {
    return { "X-CMS-Admin-Token": obj.adminToken };
  }
  return {};
}

function csrfHeaders(path: string): Record<string, string> {
  if (path.includes("/api/auth/refresh")) {
    const csrf = getCsrfToken();
    return csrf ? { "X-CSRF-Token": csrf } : {};
  }
  return {};
}

/**
 * Attempt a silent token refresh. On success the new access_token is stored
 * and returned. On failure returns null.
 */
async function silentRefresh(): Promise<string | null> {
  try {
    const csrf = getCsrfToken();
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { access_token?: string };
    if (data.access_token) {
      setAccessToken(data.access_token);
      return data.access_token;
    }
    return null;
  } catch {
    return null;
  }
}

function redirectToLogin(): void {
  window.location.href = "/login";
}

// ─── core request ────────────────────────────────────────────────────────────

async function request<T>(
  path: string,
  init: RequestInit,
  auth: ApiAuth,
  isRetry = false
): Promise<T> {
  const authHdrs = resolveAuthHeaders(auth);
  const csrf = csrfHeaders(path);

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.headers as Record<string, string> | undefined),
      ...authHdrs,
      ...csrf,
    },
  });

  if (response.status === 401 && !isRetry) {
    const isJwt = "jwt" in auth && auth.jwt;
    if (isJwt) {
      const newToken = await silentRefresh();
      if (newToken) {
        // Retry once with the refreshed token
        return request<T>(path, init, auth, true);
      }
      redirectToLogin();
      // Promise never resolves after redirect — throw to stop execution
      throw new Error("Session expired");
    }
  }

  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

// ─── public API ──────────────────────────────────────────────────────────────

export async function apiGet<T>(path: string, auth: ApiAuth): Promise<T> {
  return request<T>(path, {}, auth);
}

export async function apiPatch<T>(
  path: string,
  auth: ApiAuth,
  body: unknown
): Promise<T> {
  return request<T>(
    path,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    auth
  );
}

export async function apiPost<T>(
  path: string,
  auth: ApiAuth,
  body: unknown
): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    auth
  );
}

export async function apiDelete<T>(path: string, auth: ApiAuth): Promise<T> {
  return request<T>(path, { method: "DELETE" }, auth);
}

export async function apiUpload<T>(
  path: string,
  auth: ApiAuth,
  files: File[],
  fieldName = "files"
): Promise<T> {
  const formData = new FormData();
  files.forEach((file) => formData.append(fieldName, file));
  return request<T>(path, { method: "POST", body: formData }, auth);
}

// ─── CMS-specific: unauthenticated endpoints ─────────────────────────────────

/**
 * Error thrown by `requestOtp`/`verifyOtp` on non-2xx responses or transport
 * failures. Carries the HTTP status (0 means network/CORS failure) and a
 * best-effort `detail` string from the server's JSON body.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const text = await res.text();
    if (!text) return "";
    try {
      const data = JSON.parse(text) as { detail?: string | unknown; message?: string };
      if (typeof data.detail === "string") return data.detail;
      if (typeof data.message === "string") return data.message;
    } catch {
      /* not JSON — fall through to text */
    }
    return text.slice(0, 200);
  } catch {
    return "";
  }
}

async function postUnauthed(path: string, body: unknown, withCredentials = false): Promise<Response> {
  try {
    return await fetch(`${API_BASE}${path}`, {
      method: "POST",
      credentials: withCredentials ? "include" : "omit",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    // Most commonly: CORS preflight reject, mixed-content block, DNS failure.
    const msg = err instanceof Error ? err.message : String(err);
    throw new ApiError(0, `Сеть недоступна или CORS заблокирован: ${msg}`);
  }
}

/** Request a WhatsApp OTP for the given phone number. */
export async function requestOtp(phone: string): Promise<void> {
  const res = await postUnauthed("/api/auth/otp/send", { phone });
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new ApiError(res.status, detail);
  }
}

/** Verify the OTP and return the access token. */
export async function verifyOtp(phone: string, otp: string): Promise<string> {
  const res = await postUnauthed("/api/auth/otp/verify", { phone, code: otp }, true);
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new ApiError(res.status, detail);
  }
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}

// Re-export for consumers that need token access
export { getAccessToken };
