/**
 * API client.
 *
 * Supports three auth modes:
 *   Telegram Mini App — pass initData string directly (backward-compat)
 *   CMS JWT           — pass auth: { jwt: true } to use global auth helpers (auth.ts)
 *   CMS admin token   — pass auth: { adminToken: string } for token-based access
 *
 * In CMS JWT mode a 401 triggers one silent token-refresh attempt before
 * redirecting the user to /cms/login.
 */

import {
  detectAuthMode,
  getAccessToken,
  getCsrfToken,
  getAuthHeaders,
  setAccessToken,
} from "../auth";

const API_BASE = import.meta.env.VITE_API_BASE || "";

/** Unified auth discriminator. */
export type ApiAuth =
  | string
  | { jwt: true }
  | { telegramInitData?: string; adminToken?: string };

// ─── internal helpers ────────────────────────────────────────────────────────

function resolveAuthHeaders(auth: ApiAuth): Record<string, string> {
  if (typeof auth === "string") {
    // Legacy Telegram path: caller passes initData directly
    return auth ? { "X-Telegram-Init-Data": auth } : {};
  }
  if ("jwt" in auth && auth.jwt) {
    // CMS / global-auth path
    return getAuthHeaders();
  }
  // Admin token / telegramInitData object path
  const obj = auth as { telegramInitData?: string; adminToken?: string };
  if (obj.telegramInitData) {
    return { "X-Telegram-Init-Data": obj.telegramInitData };
  }
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
  window.location.href = "/cms/login";
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
    const isJwt = typeof auth !== "string" && "jwt" in auth && auth.jwt;
    if (isJwt || detectAuthMode() === "cms") {
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

/** Request a WhatsApp OTP for the given phone number. */
export async function requestOtp(phone: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/auth/otp/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) throw new Error(`OTP request failed: ${res.status}`);
}

/** Verify the OTP and return the access token. */
export async function verifyOtp(phone: string, otp: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/auth/otp/verify`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, otp }),
  });
  if (!res.ok) throw new Error(`OTP verify failed: ${res.status}`);
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}

// Re-export for consumers that need token access
export { getAccessToken };
