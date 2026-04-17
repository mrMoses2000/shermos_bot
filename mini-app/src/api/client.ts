const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function apiGet<T>(path: string, initData: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "X-Telegram-Init-Data": initData
    }
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPatch<T>(path: string, initData: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiPost<T>(path: string, initData: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiDelete<T>(path: string, initData: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: {
      "X-Telegram-Init-Data": initData
    }
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiUpload<T>(
  path: string,
  initData: string,
  files: File[],
  fieldName: string = "files"
): Promise<T> {
  const formData = new FormData();
  files.forEach(file => formData.append(fieldName, file));
  
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "X-Telegram-Init-Data": initData
    },
    body: formData
  });
  if (!response.ok) {
    throw new Error(`API error ${response.status}`);
  }
  return (await response.json()) as T;
}
