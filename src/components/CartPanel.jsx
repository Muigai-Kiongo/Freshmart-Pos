import { useState } from "react";
import { Minus, Plus, Trash2, ShoppingCart, X } from "lucide-react";
import { money } from "../utils";

export default function CartPanel({ cart, subtotal, vat, total, onAdd, onDecrease, onRemove, onClear, onCheckout }) {
  const [open, setOpen] = useState(false);
  const count = cart.reduce((n, i) => n + i.qty, 0);

  const inner = (
    <>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-700 text-white">
            <ShoppingCart size={15} />
          </div>
          <div>
            <p className="text-sm font-extrabold text-brand-950">Current sale</p>
            <p className="text-xs text-gray-400">{count} {count === 1 ? "item" : "items"}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {cart.length > 0 && (
            <button onClick={onClear} className="rounded-lg px-2.5 py-1 text-xs font-semibold text-red-500 hover:bg-red-50">
              Clear all
            </button>
          )}
          <button onClick={() => setOpen(false)} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 lg:hidden">
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Items */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {cart.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 text-brand-300">
              <ShoppingCart size={28} />
            </div>
            <p className="text-sm font-semibold text-gray-500">No items yet</p>
            <p className="max-w-44 text-xs text-gray-400">Tap a product to start a sale.</p>
          </div>
        ) : (
          <ul className="space-y-2">
            {cart.map((item) => (
              <li key={item.id} className="flex items-center gap-3 rounded-xl border border-gray-100 bg-gray-50 p-2.5">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white shadow-sm">
                  <i className={`bi ${item.icon} text-xl text-brand-700`} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-semibold text-gray-800">{item.name}</p>
                  <p className="text-[11px] text-gray-400">{money(item.price)} each</p>
                  <div className="mt-1.5 flex items-center gap-1">
                    <button aria-label="Decrease" onClick={() => onDecrease(item.id)}
                      className="flex h-5 w-5 items-center justify-center rounded-md bg-white ring-1 ring-gray-200 hover:bg-gray-100">
                      <Minus size={10} />
                    </button>
                    <span className="w-6 text-center text-xs font-bold text-gray-800">{item.qty}</span>
                    <button aria-label="Increase" onClick={() => onAdd(item)} disabled={item.qty >= item.stock}
                      className="flex h-5 w-5 items-center justify-center rounded-md bg-white ring-1 ring-gray-200 hover:bg-gray-100 disabled:opacity-40">
                      <Plus size={10} />
                    </button>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <p className="text-sm font-extrabold text-brand-800">{money(item.price * item.qty)}</p>
                  <button aria-label={`Remove ${item.name}`} onClick={() => onRemove(item.id)}
                    className="text-gray-300 hover:text-red-500 transition">
                    <Trash2 size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Totals + Checkout */}
      <div className="border-t border-gray-100 px-5 pb-5 pt-4">
        <div className="space-y-1.5 text-sm">
          <div className="flex justify-between text-gray-400">
            <span>Subtotal</span><span>{money(subtotal)}</span>
          </div>
          <div className="flex justify-between text-gray-400">
            <span>VAT</span><span>{money(vat)}</span>
          </div>
          <div className="flex justify-between border-t border-dashed border-gray-200 pt-2 text-base font-extrabold text-brand-950">
            <span>Total</span><span>{money(total)}</span>
          </div>
        </div>
        <button
          onClick={() => { onCheckout(); setOpen(false); }}
          disabled={cart.length === 0}
          className="mt-4 w-full rounded-xl bg-brand-700 py-3.5 text-sm font-extrabold text-white shadow-lg shadow-brand-700/25 transition hover:bg-brand-800 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        >
          Checkout · {money(total)}
        </button>
      </div>
    </>
  );

  return (
    <>
      {/* Desktop panel */}
      <aside className="hidden lg:flex min-h-0 w-[340px] xl:w-[380px] shrink-0 flex-col bg-white border-l border-gray-100">
        {inner}
      </aside>

      {/* Mobile: floating cart button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-20 right-4 z-30 flex items-center gap-2 rounded-2xl bg-brand-700 px-4 py-3 text-sm font-bold text-white shadow-xl shadow-brand-700/30 lg:hidden"
        >
          <ShoppingCart size={18} />
          {count > 0 && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[10px] font-bold text-brand-950">
              {count}
            </span>
          )}
          {count > 0 ? money(total) : "Cart"}
        </button>
      )}

      {/* Mobile: slide-up drawer */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="absolute bottom-0 left-0 right-0 flex max-h-[85dvh] flex-col rounded-t-3xl bg-white shadow-2xl">
            {inner}
          </div>
        </div>
      )}
    </>
  );
}
