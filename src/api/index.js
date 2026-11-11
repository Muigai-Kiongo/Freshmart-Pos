// ─────────────────────────────────────────────────────────────────────────────
// index.js  (the API gateway)
//
// This is the ONLY file that the rest of the app imports from.
// No screen or component should ever import directly from mock.js, client.js,
// or mappers.js — everything goes through here.
//
// Each function here:
//   1. Decides whether to call the mock or the real backend (via stub())
//   2. Passes the raw response through a mapper to get a clean, consistent shape
//   3. Is clearly labelled as either WIRED (real endpoint exists) or NOT WIRED YET
//
// When your teammate builds a new backend endpoint, they:
//   1. Find the matching function below
//   2. Replace the null in stub() with the real request() call
//   3. That's it — the UI doesn't need to change at all
// ─────────────────────────────────────────────────────────────────────────────

import { USE_MOCK, stub, NotImplementedError } from "./config";
import { request } from "./client";
import { toProduct, toSale } from "./mappers";
import {
  mockGetUser, mockGetProducts, mockGetSales,
  mockCreateSale, mockLogin, mockMpesaStk, mockCardCharge,
} from "./mock";

// Re-export so components can catch this error type without importing from config
export { NotImplementedError };

// ─── WIRED ───────────────────────────────────────────────────────────────────
// These endpoints have a real backend counterpart ready.
// In mock mode they use the mock. In real mode they call the actual server.

// Fetches the currently logged-in user's profile (name, role).
// Called once on app load to personalise the header and receipt.
export const getCurrentUser = () =>
  stub("getCurrentUser", mockGetUser, () => request("/auth/me"));

// Fetches all products from the store.
// Called on load and again after each sale to refresh stock levels.
export async function getProducts() {
  const raw = await stub("getProducts", mockGetProducts, () => request("/products"));
  return raw.map(toProduct); // normalise to a consistent shape
}

// Fetches today's completed sales.
// Used to populate the stats strip (total revenue, transaction count, items sold).
export async function getSales() {
  const raw = await stub("getSales", mockGetSales, () => request("/sales?date=today"));
  return raw.map(toSale);
}

// Records a completed sale on the backend and reduces stock accordingly.
// payload = { items, paymentMethod, reference, amountTendered, phone? }
export async function createSale(payload) {
  const raw = await stub("createSale", () => mockCreateSale(payload), () =>
    request("/sales", { method: "POST", body: payload })
  );
  return toSale(raw);
}

// Clears the auth token from localStorage, effectively logging the user out.
// The backend session is not explicitly invalidated — token just stops being sent.
export function logout() {
  try { localStorage.removeItem("fm_token"); } catch { /* ignore */ }
}

// ─── NOT WIRED YET ───────────────────────────────────────────────────────────
// These work perfectly in mock mode for development and demos.
// In real mode (VITE_USE_MOCK=false) they throw NotImplementedError
// which redirects the cashier to the 403 page.
//
// To wire a real endpoint, replace null with the actual request() call.

// Authenticates a cashier with email + password.
// On success the login page should save the token:
//   localStorage.setItem("fm_token", result.token)
//   localStorage.setItem("fm_user_name", result.user.name)
//   localStorage.setItem("fm_user_role", result.user.role)
export async function login(email, password) {
  return stub("login", () => mockLogin(email, password), null);
  // TODO: replace null with:
  // () => request("/auth/login", { method: "POST", body: { email, password } })
}

// Sends an M-Pesa STK push prompt to the customer's phone.
// The customer sees a payment request pop up on their phone and enters their PIN.
// Returns a checkoutRequestId used to verify payment completion.
export async function mpesaStkPush(phone, amount) {
  return stub("mpesaStkPush", () => mockMpesaStk(phone, amount), null);
  // TODO: replace null with real Safaricom Daraja API call
}

// Charges a card through the payment gateway.
// last4 is the last 4 digits shown on the card machine slip after approval.
export async function cardCharge(last4, amount) {
  return stub("cardCharge", () => mockCardCharge(last4, amount), null);
  // TODO: replace null with real card gateway call
}
