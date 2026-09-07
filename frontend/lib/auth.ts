"""前端认证工具 — token 存储 + API 注入 Authorization"""
const TOKEN_KEY = "temu_token";
const USER_KEY = "temu_user";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: string;
  shop_id: string | null;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function setAuth(token: string, user: User) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(url, { ...init, headers });
  if (resp.status === 401) {
    clearAuth();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  return resp;
}

// ============ 权限矩阵（与后端对齐）============
const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  admin: new Set(["*"]),
  operator: new Set([
    "batches", "candidates.view", "reviews.first", "audit.view",
  ]),
  editor: new Set([
    "candidates.view", "listings.edit", "reviews.first",
  ]),
  reviewer: new Set([
    "candidates.view", "reviews.first", "reviews.second", "listings.view",
  ]),
  publisher: new Set([
    "listings.view", "publish.execute", "publish.retry",
  ]),
  readonly: new Set([
    "batches.view", "candidates.view", "listings.view", "audit.view",
  ]),
};

export function hasPermission(perm: string): boolean {
  const user = getUser();
  if (!user) return false;
  const perms = ROLE_PERMISSIONS[user.role] || new Set();
  return perms.has("*") || perms.has(perm);
}