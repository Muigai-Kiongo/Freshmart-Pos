// ─────────────────────────────────────────────────────────────────────────────
// client.js
//
// The low-level HTTP layer. This is the only file that calls fetch().
// Every real API request in the app goes through the request() function here.
// The mock bypasses this file entirely — it never makes network calls.
// ─────────────────────────────────────────────────────────────────────────────

import { API_URL } from "./config";

// Reads the auth token that the login page saves after a successful login.
// The token is attached to every request so the backend knows who is calling.
// If there is no token (user not logged in), requests are sent without one
// and the backend will return 401 which triggers a redirect to login.
export const getToken = () => {
  try { return localStorage.getItem("fm_token"); } catch { return null; }
};

// ─── request() ───────────────────────────────────────────────────────────────
// Makes an authenticated HTTP request to the backend.
//
// path   — the endpoint path e.g. "/products" or "/sales"
// method — HTTP verb, defaults to "GET"
// body   — optional JavaScript object, automatically JSON-stringified
//
// Returns the parsed response data on success.
// Throws a descriptive error on failure so the UI can show a message
// instead of silently failing.
//
// Special cases handled:
//   • Network error (server down) → clear message to check the backend
//   • 401 Unauthorized → session expired message (triggers logout in App.jsx)
//   • Any other non-OK status → uses the backend's error message if available
//   • Backend may wrap data in { data: ... } or return it directly — both work
export async function request(path, { method = "GET", body } = {}) {
  const token = getToken();
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        // Only attach the Authorization header if a token exists
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    // fetch() itself threw — this means the server is unreachable
    throw new Error("Can't reach the server. Check that the backend is running.");
  }

  // Try to parse the response body as JSON, fall back to null if it's not JSON
  const data = await res.json().catch(() => null);

  if (res.status === 401) {
    throw Object.assign(new Error("Your session has expired. Please log in again."), { status: 401 });
  }
  if (!res.ok) {
    throw Object.assign(new Error(data?.message ?? `Request failed (${res.status})`), { status: res.status });
  }

  // Support both { data: [...] } and [...] response shapes from the backend
  return data?.data ?? data;
}
