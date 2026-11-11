// ─────────────────────────────────────────────────────────────────────────────
// mock.js  (the fake backend)
//
// Simulates a real backend entirely in memory — no server needed.
// Active when VITE_USE_MOCK=true (the default).
//
// This lets anyone clone the project and run it immediately without
// setting up a database or backend server.
//
// Data resets every time the page is refreshed (lives in memory only).
// Products start from the seed data in data/products.js.
// ─────────────────────────────────────────────────────────────────────────────

import { products as seed } from "../data/products";

// In-memory store — starts as a fresh copy of the seed products each page load
let products = seed.map((p) => ({ ...p }));
let sales = [];

// Simulates network latency so the UI loading states actually show during dev
const wait = (ms = 350) => new Promise((r) => setTimeout(r, ms));

// The logged-in user. Reads from localStorage so the real name shows once
// the login page saves it. Falls back to "Cashier" until then.
export const mockUser = {
  id: 1,
  name: localStorage.getItem("fm_user_name") || "Cashier",
  role: localStorage.getItem("fm_user_role") || "Cashier",
};

// ─── Auth ─────────────────────────────────────────────────────────────────────

// Returns the current user — called on app load to populate the header
export async function mockGetUser() {
  await wait(150);
  return mockUser;
}

// Validates demo credentials and saves the user's name/role to localStorage
// so the header shows the real name on the next load.
// Demo: cashier@freshmart.co.ke / demo1234
export async function mockLogin(email, password) {
  await wait(800);
  if (email === "cashier@freshmart.co.ke" && password === "demo1234") {
    const user = { id: 1, name: "Amina Wanjiru", role: "Cashier" };
    localStorage.setItem("fm_user_name", user.name);
    localStorage.setItem("fm_user_role", user.role);
    return { token: "mock-token-xyz", user };
  }
  throw Object.assign(new Error("Invalid email or password."), { status: 401 });
}

// ─── Products ─────────────────────────────────────────────────────────────────

// Returns a copy of the current product list (with live stock levels)
export async function mockGetProducts() {
  await wait();
  return products.map((p) => ({ ...p }));
}

// ─── Sales ────────────────────────────────────────────────────────────────────

// Returns all sales recorded this session
export async function mockGetSales() {
  await wait();
  return sales;
}

// Records a new sale and reduces stock for each sold item.
// Calculates VAT per item using each product's individual vatRate
// (exempt items like bread and milk contribute zero VAT).
export async function mockCreateSale(payload) {
  await wait(500);

  const subtotal = payload.items.reduce((s, i) => s + i.price * i.qty, 0);
  const vat = payload.items.reduce((s, i) => {
    const rate = i.vatRate ?? 0.16;
    // null vatRate means exempt — no VAT charged
    return rate === null ? s : s + i.price * i.qty * rate;
  }, 0);
  const total = subtotal + vat;

  // Reduce stock for each item sold
  products = products.map((p) => {
    const sold = payload.items.find((i) => i.productId === p.id);
    return sold ? { ...p, stock: p.stock - sold.qty } : p;
  });

  const sale = {
    receiptNo:      `FM-${Date.now().toString().slice(-8)}`,
    createdAt:      new Date().toISOString(),
    cashier:        mockUser.name,
    items:          payload.items,
    subtotal, vat, total,
    paymentMethod:  payload.paymentMethod,
    reference:      payload.reference,
    amountTendered: payload.amountTendered,
    change:         Math.max(0, payload.amountTendered - total),
  };

  // Prepend so the most recent sale appears first
  sales = [sale, ...sales];
  return sale;
}

// ─── Payments (mock only — not wired to real backend) ─────────────────────────

// Simulates sending an M-Pesa STK push to the customer's phone.
// Has a 10% random failure rate to let you test the error handling flow.
export async function mockMpesaStk(phone, amount) {
  await wait(1800);
  if (Math.random() < 0.1) throw new Error("STK push timed out. Ask customer to try again.");
  return { checkoutRequestId: `mock-stk-${Date.now()}`, phone, amount };
}

// Simulates a card payment gateway approval
export async function mockCardCharge(last4, amount) {
  await wait(1200);
  return { approved: true, reference: `CARD-****${last4}`, amount };
}
