// ─────────────────────────────────────────────────────────────────────────────
// mappers.js  (data normalisation)
//
// The backend and the mock may return data in slightly different shapes
// depending on who built them. Mappers convert any raw response into a
// single consistent shape that the rest of the app always expects.
//
// This means if the backend changes a field name (e.g. "quantity" → "stock"),
// you fix it in ONE place here — not across every component.
// ─────────────────────────────────────────────────────────────────────────────

// Converts a raw product from the API/mock into the shape the UI expects.
// Handles field name differences between backends:
//   id     — supports both "id" (REST) and "_id" (MongoDB)
//   stock  — supports "stock" or "quantity"
//   image  — supports "image" or "imageUrl"
//   category — supports a nested object { name: "Fruits" } or a plain string
export const toProduct = (r) => ({
  id:       r.id ?? r._id,
  name:     r.name,
  price:    Number(r.price),
  category: r.category?.name ?? r.category ?? "Other",
  stock:    Number(r.stock ?? r.quantity ?? 0),
  image:    r.image ?? r.imageUrl ?? null,
  icon:     r.icon ?? "bi-bag",
  barcode:  r.barcode ?? null,
});

// Converts a raw sale from the API/mock into the shape the UI expects.
// Handles field name differences:
//   id       — supports "receiptNo", "id", or "_id"
//   date     — converts ISO string to a real JavaScript Date object
//   cashier  — supports a nested object { name: "..." } or a plain string
//   method   — supports "paymentMethod" or "method"
//   tendered — supports "amountTendered", "tendered", or falls back to total
//   items    — normalises each line item and preserves vatRate for receipt display
export const toSale = (r) => ({
  id:       r.receiptNo ?? r.id ?? r._id,
  date:     new Date(r.createdAt ?? r.date ?? Date.now()),
  cashier:  r.cashier?.name ?? r.cashier ?? "",
  method:   r.paymentMethod ?? r.method,
  reference: r.reference ?? null,
  tendered: Number(r.amountTendered ?? r.tendered ?? r.total),
  change:   Number(r.change ?? 0),
  subtotal: Number(r.subtotal),
  vat:      Number(r.vat),
  total:    Number(r.total),
  items: (r.items ?? []).map((i) => ({
    id:      i.productId ?? i.id,
    name:    i.name,
    price:   Number(i.price),
    qty:     Number(i.qty ?? i.quantity),
    vatRate: i.vatRate ?? 0.16, // preserved so the receipt can show "Exempt" labels
  })),
});
