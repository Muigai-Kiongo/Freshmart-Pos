import { useCallback, useEffect, useState } from "react";
import { getCurrentUser, getProducts, getSales, logout } from "./api";
import { cartTotals } from "./utils";
import { STORE } from "./config";
import Sidebar from "./components/Sidebar";
import CartPanel from "./components/CartPanel";
import CheckoutModal from "./components/CheckoutModal";
import Terminal from "./pages/Terminal";

const titles = {
  terminal: "Cashier terminal",
};

export default function App() {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [page, setPage] = useState("terminal");
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState([]);
  const [sales, setSales] = useState([]);
  const [checkingOut, setCheckingOut] = useState(false);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [u, p, s] = await Promise.all([getCurrentUser(), getProducts(), getSales()]);
      setUser(u); setProducts(p); setSales(s);
      setStatus("ready");
    } catch (e) {
      if (e.status === 401) { setStatus("loggedout"); return; }
      setError(e.message);
      setStatus("error");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const { subtotal, vat, total } = cartTotals(cart);

  function addToCart(product) {
    setCart((prev) => {
      const found = prev.find((i) => i.id === product.id);
      if (found) {
        if (found.qty >= product.stock) return prev;
        return prev.map((i) => (i.id === product.id ? { ...i, qty: i.qty + 1 } : i));
      }
      return [...prev, { ...product, qty: 1 }];
    });
  }

  const decrease = (id) =>
    setCart((prev) => prev.map((i) => (i.id === id ? { ...i, qty: i.qty - 1 } : i)).filter((i) => i.qty > 0));
  const remove = (id) => setCart((prev) => prev.filter((i) => i.id !== id));

  async function finishSale(sale) {
    setSales((prev) => [sale, ...prev]);
    setCart([]);
    setCheckingOut(false);
    try { setProducts(await getProducts()); } catch { /* keep old list */ }
  }

  function handleLogout() {
    logout();
    setCart([]);
    setStatus("loggedout");
  }

  if (status === "loading") {
    return (
      <div className="flex h-dvh items-center justify-center bg-brand-950 text-white">
        <p className="animate-pulse text-lg font-semibold">Loading {STORE.name} POS…</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex h-dvh items-center justify-center bg-brand-950 p-6">
        <div className="max-w-md rounded-2xl bg-white p-8 text-center">
          <h1 className="text-xl font-extrabold text-brand-950">Couldn't load the store</h1>
          <p className="mt-2 text-gray-600">{error}</p>
          <button onClick={load} className="mt-5 rounded-xl bg-accent px-6 py-3 font-bold text-brand-950">Try again</button>
        </div>
      </div>
    );
  }

  if (status === "loggedout") {
    return (
      <div className="flex h-dvh items-center justify-center bg-brand-950">
        <button onClick={load} className="rounded-xl bg-accent px-6 py-3 font-bold text-brand-950">
          Go to login (placeholder)
        </button>
      </div>
    );
  }

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <div className="flex h-dvh">
      <Sidebar page={page} setPage={setPage} user={user} onLogout={handleLogout} />

      {/* Main content — offset for mobile top bar (h-14) and bottom nav (h-14) */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden pt-14 pb-14 lg:pt-0 lg:pb-0">
        {/* Desktop header */}
        <header className="hidden items-center justify-between border-b border-gray-100 bg-white px-6 py-4 shadow-sm lg:flex">
          <div>
            <h1 className="text-xl font-extrabold text-brand-950">{titles[page]}</h1>
            <p className="text-xs text-gray-400">
              {greeting}, {user.name === "Cashier" ? "there" : user.name.split(" ")[0]} · {new Date().toLocaleDateString(STORE.locale, { weekday: "long", day: "numeric", month: "long" })}
            </p>
          </div>
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-700 font-bold text-white text-sm shadow">
            {user.name[0]}
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
          {page === "terminal" && (
            <>
              <Terminal products={products} cart={cart} sales={sales} onAdd={addToCart} />
              <CartPanel
                cart={cart} subtotal={subtotal} vat={vat} total={total}
                onAdd={addToCart} onDecrease={decrease} onRemove={remove}
                onClear={() => setCart([])} onCheckout={() => setCheckingOut(true)}
              />
            </>
          )}
        </div>
      </div>

      {checkingOut && (
        <CheckoutModal
          cart={cart} subtotal={subtotal} vat={vat} total={total} cashier={user.name}
          onClose={() => setCheckingOut(false)} onComplete={finishSale}
        />
      )}
    </div>
  );
}
