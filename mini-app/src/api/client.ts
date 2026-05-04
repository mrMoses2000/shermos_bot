const API_BASE = import.meta.env.VITE_API_BASE || "";

export type ApiAuth = string | {
  telegramInitData?: string;
  adminToken?: string;
};

function authHeaders(auth: ApiAuth): Record<string, string> {
  if (typeof auth === "string") {
    return auth ? { "X-Telegram-Init-Data": auth } : {};
  }
  if (auth.telegramInitData) {
    return { "X-Telegram-Init-Data": auth.telegramInitData };
  }
  if (auth.adminToken) {
    return { "X-CMS-Admin-Token": auth.adminToken };
  }
  return {};
}

export async function apiGet<T>(path: string, auth: ApiAuth): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders(auth)
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPatch<T>(path: string, auth: ApiAuth, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(auth)
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, auth: ApiAuth, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(auth)
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiDelete<T>(path: string, auth: ApiAuth): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: authHeaders(auth)
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiUpload<T>(
  path: string,
  auth: ApiAuth,
  files: File[],
  fieldName: string = "files"
): Promise<T> {
  const formData = new FormData();
  files.forEach(file => formData.append(fieldName, file));
  
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authHeaders(auth),
    body: formData
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}
