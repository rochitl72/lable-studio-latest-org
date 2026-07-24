// Authentication against the backend.
//
// Credentials are verified server-side; this module only holds the JWT the
// server issues. Nothing secret lives in this file.

const TOKEN_KEY = "rbg-studio-token";

// The current signed-in user (id, username, role, must_change_password …).
// Held in memory and refreshed from /api/auth/me; the whole role-based UI
// branches on this.
let currentUser = null;

export function getCurrentUser() {
  return currentUser;
}

export function isAdmin() {
  return currentUser?.role === "admin";
}

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function isAuthenticated() {
  return !!getToken();
}

export function setToken(token) {
  if (token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  } else {
    sessionStorage.removeItem(TOKEN_KEY);
  }
}

/** Fetch the signed-in user from the server and cache it. Returns the user or null. */
export async function fetchCurrentUser() {
  if (!getToken()) {
    currentUser = null;
    return null;
  }
  try {
    const r = await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!r.ok) {
      currentUser = null;
      return null;
    }
    currentUser = await r.json();
    return currentUser;
  } catch {
    return currentUser;
  }
}

/** Drop the local token and ask the server to clear the image cookie. */
export async function logout() {
  const token = getToken();
  setToken(null);
  currentUser = null;
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch {
    // Already signed out locally; a failed call here doesn't matter.
  }
}

/**
 * Exchange username + password for a token.
 * Returns { ok: true } or { ok: false, error: "..." }.
 */
export async function login(username, password) {
  let r;
  try {
    r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    return { ok: false, error: "Cannot reach the server. Is the backend running?" };
  }

  if (r.status === 401) {
    return { ok: false, error: "Incorrect username or password." };
  }
  if (!r.ok) {
    return { ok: false, error: `Login failed (${r.status}).` };
  }

  const data = await r.json();
  setToken(data.access_token);
  currentUser = data.user || null;
  return { ok: true };
}

/** Check a stored token is still valid — it may have expired between visits.
 *  Also caches the current user so the UI knows the role immediately. */
export async function verifyToken() {
  if (!getToken()) return false;
  try {
    const r = await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!r.ok) {
      setToken(null);
      currentUser = null;
      return false;
    }
    currentUser = await r.json();
    return true;
  } catch {
    // Network error rather than a rejection — keep the token and let the
    // user retry instead of bouncing them to the login screen.
    return true;
  }
}
