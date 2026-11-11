import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { X, Banknote, Smartphone, CreditCard, Printer, CheckCircle2, ShieldCheck, Loader2 } from "lucide-react";
import { money, VAT } from "../utils";
import { createSale, mpesaStkPush, cardCharge, NotImplementedError } from "../api";
import { WIRED } from "../api/config";
import { STORE } from "../config";

const METHODS = [
  { id: "cash",  label: "Cash",   icon: Banknote },
  { id: "mpesa", label: "M-Pesa", icon: Smartphone },
  { id: "card",  label: "Card",   icon: CreditCard },
];

function isValidKEPhone(v) {
  return /^(?:\+?254|0)[17]\d{8}$/.test(v.replace(/\s/g, ""));
}

function normalisePhone(v) {
  const d = v.replace(/\s/g, "");
  if (d.startsWith("+254")) return d;
  if (d.startsWith("254"))  return `+${d}`;
  if (d.startsWith("0"))    return `+254${d.slice(1)}`;
  return d;
}

export default function CheckoutModal({ cart, subtotal, vat, total, cashier, onClose, onComplete }) {
  const navigate = useNavigate();

  const [method, setMethod]     = useState("cash");
  const [tendered, setTendered] = useState("");
  const [phone, setPhone]       = useState("");
  const [stkSent, setStkSent]   = useState(false);
  const [mpesaCode, setMpesaCode] = useState("");
  const [last4, setLast4]       = useState("");

  const [sale, setSale]                     = useState(null);
  const [paymentVerified, setPaymentVerified] = useState(false);
  const [submitting, setSubmitting]         = useState(false);
  const [stkLoading, setStkLoading]         = useState(false);
  const [verifying, setVerifying]           = useState(false);
  const [error, setError]                   = useState("");

  const tenderedNum = Number(tendered) || 0;
  const change = Math.max(0, tenderedNum - total);

  const canPay =
    method === "cash"  ? tenderedNum >= total :
    method === "mpesa" ? stkSent && mpesaCode.trim().length >= 6 :
    last4.trim().length === 4 && /^\d{4}$/.test(last4.trim());

  const quick = [...new Set([
    Math.ceil(total),
    Math.ceil(total / 100) * 100,
    Math.ceil(total / 500) * 500,
    Math.ceil(total / 1000) * 1000,
  ])].slice(0, 4);

  function switchMethod(id) {
    if (id === "mpesa" && !WIRED.mpesa) { onClose(); navigate("/403"); return; }
    if (id === "card"  && !WIRED.card)  { onClose(); navigate("/403"); return; }
    setMethod(id);
    setTendered(""); setPhone(""); setStkSent(false);
    setMpesaCode(""); setLast4(""); setError("");
  }

  async function sendStk() {
    if (!isValidKEPhone(phone)) { setError("Enter a valid Kenyan phone number."); return; }
    setError("");
    setStkLoading(true);
    try {
      await mpesaStkPush(normalisePhone(phone), total);
      setStkSent(true);
    } catch (e) {
      setError(e.message || "Failed to send STK push. Try again.");
    } finally {
      setStkLoading(false);
    }
  }

  async function pay() {
    setSubmitting(true);
    setError("");
    const ref =
      method === "mpesa" ? mpesaCode.trim().toUpperCase() :
      method === "card"  ? `CARD-****${last4.trim()}` :
      null;
    try {
      if (method === "card") await cardCharge(last4.trim(), total);
      const created = await createSale({
        items: cart.map((i) => ({ productId: i.id, name: i.name, price: i.price, qty: i.qty, vatRate: i.vatRate ?? 0.16 })),
        paymentMethod: method,
        reference: ref,
        amountTendered: method === "cash" ? tenderedNum : total,
        phone: method === "mpesa" ? normalisePhone(phone) : undefined,
      });
      setSale(created);
      setVerifying(true);
      await new Promise((r) => setTimeout(r, method === "cash" ? 600 : 1200));
      setVerifying(false);
      setPaymentVerified(true);
    } catch (e) {
      if (e instanceof NotImplementedError) {
        onClose(); navigate("/403");
      } else {
        setError(e.message || "Payment could not be saved. Try again.");
      }
      setVerifying(false);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-brand-950/70 backdrop-blur-sm sm:items-center sm:p-4">
      <div className="flex max-h-[95dvh] w-full max-w-3xl flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl">
        <div className="overflow-y-auto">
          {!sale ? (
            <div className="grid md:grid-cols-[1fr_1.1fr]">
              {/* Order summary */}
              <div className="bg-gradient-to-b from-brand-950 to-brand-800 p-6 text-white md:p-7">
                <h2 className="text-lg font-bold">Order summary</h2>
                <ul className="mt-4 max-h-48 space-y-2 overflow-y-auto pr-1 text-sm">
                  {cart.map((i) => (
                    <li key={i.id} className="flex justify-between gap-3">
                      <span className="text-white/80">
                        {i.qty} × {i.name}
                        {i.vatRate === VAT.EXEMPT && (
                          <span className="ml-1.5 rounded bg-white/15 px-1 py-0.5 text-[10px] font-semibold">Exempt</span>
                        )}
                      </span>
                      <span className="font-semibold">{money(i.price * i.qty)}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-5 border-t border-white/15 pt-4 space-y-3">
                  <div>
                    <p className="text-xs text-white/50">Customer pays</p>
                    <p className="text-4xl font-extrabold text-accent">{money(total)}</p>
                  </div>
                  <div className="space-y-1 text-sm text-white/60">
                    <div className="flex justify-between"><span>Subtotal</span><span>{money(subtotal)}</span></div>
                    <div className="flex justify-between"><span>VAT (16% on taxable)</span><span>{money(vat)}</span></div>
                  </div>
                </div>
              </div>

              {/* Payment */}
              <div className="p-6 md:p-7">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-extrabold text-brand-950">Payment method</h2>
                  <button aria-label="Close" onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
                    <X />
                  </button>
                </div>

                <div className="mt-4 grid grid-cols-3 gap-2">
                  {METHODS.map(({ id, label, icon: Icon }) => {
                    const locked = (id === "mpesa" && !WIRED.mpesa) || (id === "card" && !WIRED.card);
                    return (
                      <button
                        key={id}
                        onClick={() => switchMethod(id)}
                        className={`relative flex flex-col items-center gap-1.5 rounded-xl border-2 py-3.5 text-sm font-semibold transition ${
                          method === id ? "border-brand-700 bg-brand-100 text-brand-800" : "border-gray-200 text-gray-500 hover:border-gray-300"
                        }`}
                      >
                        <Icon size={22} /> {label}
                        {locked && (
                          <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] text-white">
                            <i className="bi bi-lock-fill" />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-5 min-h-52">
                  {/* ── CASH ── */}
                  {method === "cash" && (
                    <>
                      <label className="mb-1.5 block text-sm font-semibold">Amount received</label>
                      <input
                        type="number" min="0" inputMode="decimal" autoFocus
                        value={tendered} onChange={(e) => setTendered(e.target.value)}
                        placeholder="0.00"
                        className="w-full rounded-xl border border-gray-300 bg-gray-50 px-4 py-3 text-xl font-bold focus:border-brand-700 focus:bg-white focus:outline-none"
                      />
                      <div className="mt-2 flex flex-wrap gap-2">
                        {quick.map((q) => (
                          <button key={q} onClick={() => setTendered(String(q))}
                            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium hover:border-brand-700 hover:bg-brand-50">
                            {money(q)}
                          </button>
                        ))}
                      </div>
                      <div className="mt-3 flex items-center justify-between rounded-xl bg-brand-50 px-4 py-3">
                        <span className="text-sm font-medium text-gray-600">Change due</span>
                        <span className="text-xl font-extrabold text-brand-800">{money(change)}</span>
                      </div>
                      {tenderedNum > 0 && tenderedNum < total && (
                        <p className="mt-2 text-sm text-red-600">Short by {money(total - tenderedNum)}.</p>
                      )}
                    </>
                  )}

                  {/* ── M-PESA ── */}
                  {method === "mpesa" && (
                    !stkSent ? (
                      <>
                        <label className="mb-1.5 block text-sm font-semibold">Customer's M-Pesa number</label>
                        <div className="flex gap-2">
                          <input
                            type="tel" autoFocus
                            value={phone} onChange={(e) => { setPhone(e.target.value); setError(""); }}
                            placeholder="07XX XXX XXX"
                            className="flex-1 rounded-xl border border-gray-300 bg-gray-50 px-4 py-3 text-lg font-semibold tracking-wide focus:border-brand-700 focus:bg-white focus:outline-none"
                          />
                          <button
                            onClick={sendStk}
                            disabled={stkLoading || !phone.trim()}
                            className="flex items-center gap-2 rounded-xl bg-brand-700 px-4 py-3 text-sm font-bold text-white hover:bg-brand-800 disabled:opacity-50"
                          >
                            {stkLoading ? <Loader2 size={16} className="animate-spin" /> : <Smartphone size={16} />}
                            {stkLoading ? "Sending…" : "Send"}
                          </button>
                        </div>
                        <p className="mt-2 text-xs text-gray-400">
                          An STK push of <strong>{money(total)}</strong> will be sent to this number.
                        </p>
                        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
                      </>
                    ) : (
                      <>
                        <div className="mb-3 flex items-center gap-2 rounded-xl bg-green-50 px-4 py-3 text-sm text-green-700">
                          <CheckCircle2 size={16} className="shrink-0" />
                          STK push sent to <strong>{normalisePhone(phone)}</strong>. Ask the customer to enter their PIN.
                        </div>
                        <label className="mb-1.5 block text-sm font-semibold">M-Pesa confirmation code</label>
                        <input
                          autoFocus
                          value={mpesaCode} onChange={(e) => setMpesaCode(e.target.value.toUpperCase())}
                          placeholder="e.g. SHK4T9X2QP"
                          className="w-full rounded-xl border border-gray-300 bg-gray-50 px-4 py-3 font-mono text-lg tracking-widest focus:border-brand-700 focus:bg-white focus:outline-none"
                        />
                        <p className="mt-2 text-xs text-gray-400">Enter the code from the customer's confirmation SMS.</p>
                        <button onClick={() => { setStkSent(false); setMpesaCode(""); }} className="mt-2 text-xs text-brand-700 hover:underline">
                          ← Change number
                        </button>
                      </>
                    )
                  )}

                  {/* ── CARD ── */}
                  {method === "card" && (
                    <>
                      <div className="mb-3 rounded-xl bg-gray-50 px-4 py-3 text-sm text-gray-600 ring-1 ring-black/5">
                        <p className="font-semibold text-gray-800">Amount to charge</p>
                        <p className="mt-0.5 text-2xl font-extrabold text-brand-800">{money(total)}</p>
                        <p className="mt-1 text-xs text-gray-400">Present the card machine to the customer.</p>
                      </div>
                      <label className="mb-1.5 block text-sm font-semibold">Last 4 digits of card</label>
                      <input
                        autoFocus
                        type="text" inputMode="numeric" maxLength={4}
                        value={last4} onChange={(e) => setLast4(e.target.value.replace(/\D/g, ""))}
                        placeholder="e.g. 4782"
                        className="w-full rounded-xl border border-gray-300 bg-gray-50 px-4 py-3 font-mono text-2xl tracking-[0.5em] focus:border-brand-700 focus:bg-white focus:outline-none"
                      />
                      <p className="mt-2 text-xs text-gray-400">Shown on the card machine slip after approval.</p>
                    </>
                  )}
                </div>

                {error && <p className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
                <button
                  onClick={pay} disabled={!canPay || submitting}
                  className="mt-2 w-full rounded-xl bg-accent py-4 text-base font-extrabold text-brand-950 shadow-md shadow-accent/30 transition hover:bg-accent-dark disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  {submitting ? "Saving sale…" : "Complete payment"}
                </button>
                <p className="mt-3 flex items-center justify-center gap-1.5 text-xs text-gray-400">
                  <ShieldCheck size={14} /> Sale recorded under {cashier}
                </p>
              </div>
            </div>
          ) : (
            /* ── RECEIPT ── */
            <div className="mx-auto max-w-md p-8">
              <div className="flex flex-col items-center text-center">
                {verifying ? (
                  <>
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-amber-50 text-amber-500">
                      <Loader2 size={32} className="animate-spin" />
                    </div>
                    <h2 className="mt-3 text-xl font-extrabold text-brand-950">Confirming payment…</h2>
                    <p className="text-sm text-gray-400">Please wait, do not close this window.</p>
                  </>
                ) : (
                  <>
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-brand-100 text-brand-700">
                      <CheckCircle2 size={36} />
                    </div>
                    <h2 className="mt-3 text-xl font-extrabold text-brand-950">Payment confirmed</h2>
                    <p className="text-sm text-gray-500">
                      {sale.method === "cash"
                        ? `Give the customer ${money(sale.change)} change.`
                        : sale.method === "mpesa"
                        ? "M-Pesa payment confirmed."
                        : "Card payment approved."}
                    </p>
                  </>
                )}
              </div>

              <div id="receipt" className="mt-5 rounded-xl border border-dashed border-gray-300 p-4 font-mono text-xs leading-5 text-gray-900">
                <div className="text-center">
                  <p className="text-sm font-bold">{STORE.name}</p>
                  <p>{STORE.address}</p>
                  <p>KRA PIN: {STORE.kraPin}</p>
                  <p>Tel: {STORE.phone}</p>
                </div>
                <hr className="my-2 border-dashed border-gray-400" />
                <p>Receipt: {sale.id}</p>
                <p>Date: {sale.date.toLocaleString(STORE.locale)}</p>
                <p>Cashier: {sale.cashier}</p>
                <hr className="my-2 border-dashed border-gray-400" />
                {sale.items.map((i) => (
                  <div key={i.id} className="flex justify-between gap-2">
                    <span>
                      {i.qty} x {i.name}
                      {(i.vatRate === VAT.EXEMPT || i.vatRate === 0) && " *"}
                    </span>
                    <span>{money(i.price * i.qty)}</span>
                  </div>
                ))}
                <hr className="my-2 border-dashed border-gray-400" />
                <div className="flex justify-between"><span>Subtotal</span><span>{money(sale.subtotal)}</span></div>
                <div className="flex justify-between"><span>VAT (16%)</span><span>{money(sale.vat)}</span></div>
                <div className="flex justify-between text-sm font-bold"><span>TOTAL</span><span>{money(sale.total)}</span></div>
                <div className="flex justify-between"><span>Paid ({sale.method})</span><span>{money(sale.tendered)}</span></div>
                {sale.reference && <div className="flex justify-between"><span>Ref</span><span>{sale.reference}</span></div>}
                {sale.method === "cash" && <div className="flex justify-between"><span>Change</span><span>{money(sale.change)}</span></div>}
                <hr className="my-2 border-dashed border-gray-400" />
                <p>* VAT Exempt item</p>
                <hr className="my-2 border-dashed border-gray-400" />
                <p className="text-center">Thank you for shopping with us!</p>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3">
                <button
                  onClick={() => window.print()}
                  disabled={!paymentVerified}
                  className="flex items-center justify-center gap-2 rounded-xl border border-gray-300 py-3 font-semibold hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Printer size={18} /> Print receipt
                </button>
                <button
                  onClick={() => onComplete(sale)}
                  disabled={!paymentVerified}
                  className="rounded-xl bg-brand-700 py-3 font-bold text-white hover:bg-brand-900 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  New sale
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
