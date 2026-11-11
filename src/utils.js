// Kenya VAT rates (Finance Act 2023)
export const VAT = {
  STANDARD: 0.16,  // general goods & services
  FUEL:     0.08,  // petroleum products
  ZERO:     0.00,  // exports, zero-rated supplies
  EXEMPT:   null,  // exempt — VAT not charged at all (basic food staples, etc.)
};

// Legacy alias used across the codebase for display purposes
export const VAT_RATE = VAT.STANDARD;

export const money = (n) =>
  `KSh ${Number(n).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/**
 * Calculate VAT for a single line item.
 * vatRate === null (EXEMPT) → 0 VAT, price is final.
 */
export function lineVat(price, qty, vatRate) {
  if (vatRate === null || vatRate === 0) return 0;
  return price * qty * vatRate;
}

/**
 * Summarise cart totals respecting per-item VAT rates.
 * Returns { subtotal, vat, total }
 */
export function cartTotals(cart) {
  const subtotal = cart.reduce((s, i) => s + i.price * i.qty, 0);
  const vat      = cart.reduce((s, i) => s + lineVat(i.price, i.qty, i.vatRate ?? VAT.STANDARD), 0);
  return { subtotal, vat, total: subtotal + vat };
}
