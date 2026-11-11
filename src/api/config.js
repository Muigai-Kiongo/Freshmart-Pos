// ─────────────────────────────────────────────────────────────────────────────
// config.js
//
// The single source of truth for API settings and feature flags.
// Every other file in /api reads from here — nothing is scattered around.
// ─────────────────────────────────────────────────────────────────────────────

// The base URL for all real API requests.
// In development this defaults to http://localhost:5000/api.
// In production your teammate sets VITE_API_URL in the .env file to point
// to the live server e.g. https://api.freshmart.co.ke/api
export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:5000/api";

// Controls whether the app talks to a real backend or uses the built-in mock.
// Default is TRUE (mock on) so anyone can clone the project and run it
// without needing a backend running.
// To switch to the real backend: create a .env file and add VITE_USE_MOCK=false
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

// ─── NotImplementedError ─────────────────────────────────────────────────────
// A custom error class used to signal that a feature exists in the UI
// but hasn't been connected to a real backend endpoint yet.
// When thrown, the UI redirects to /403 instead of crashing with a
// confusing white screen or generic error message.
export class NotImplementedError extends Error {
  constructor(feature) {
    super(`"${feature}" is not connected to the backend yet.`);
    this.code = "NOT_IMPLEMENTED";
    this.feature = feature;
  }
}

// ─── stub() ──────────────────────────────────────────────────────────────────
// A helper that decides at runtime whether to call the mock or the real API.
//
// Usage:  stub("featureName", mockFunction, realFunction)
//
//   • If USE_MOCK is true  → runs mockFunction (safe, works offline)
//   • If USE_MOCK is false and realFunction is provided → runs realFunction
//   • If USE_MOCK is false and realFunction is null → throws NotImplementedError
//     meaning: "the real endpoint hasn't been built yet"
//
// This means you can add a feature to the UI today, stub it with a mock,
// and your teammate can wire the real endpoint later by replacing null
// with the actual API call — without touching any UI code.
export function stub(feature, mockFn, realFn) {
  if (USE_MOCK) return mockFn();
  if (realFn) return realFn();
  throw new NotImplementedError(feature);
}

// ─── WIRED ───────────────────────────────────────────────────────────────────
// Tracks which payment methods have been connected to a real backend.
// When false, clicking that payment method in the checkout modal redirects
// the cashier to the 403 page instead of letting them go through a flow
// that will never complete.
//
// Your teammate flips these to true once the real endpoint is ready:
//   mpesa: true  → when Safaricom Daraja STK push API is connected
//   card:  true  → when the card payment gateway is connected
export const WIRED = {
  mpesa: false,
  card:  false,
};
