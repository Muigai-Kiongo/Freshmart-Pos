import { useMemo, useState } from "react";
import { Search, Wallet, Receipt, PackageCheck, AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { money } from "../utils";
import ProductCard from "../components/ProductCard";

export default function Terminal({ products, cart, sales, onAdd }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [statsOpen, setStatsOpen] = useState(false);

  const categories = ["All", ...new Set(products.map((p) => p.category))];

  const filtered = useMemo(
    () => products.filter((p) =>
      (category === "All" || p.category === category) &&
      p.name.toLowerCase().includes(query.toLowerCase())),
    [products, query, category]
  );

  const todaySales = sales.reduce((s, x) => s + x.total, 0);
  const itemsSold  = sales.reduce((s, x) => s + x.items.reduce((n, i) => n + i.qty, 0), 0);
  const lowStock   = products.filter((p) => p.stock < 10).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">

      {/* ── Stats strip ── */}
      <div className="shrink-0 border-b border-gray-100 bg-white">
        {/* Summary row — always visible */}
        <button
          onClick={() => setStatsOpen((v) => !v)}
          className="flex w-full items-center justify-between px-4 py-2.5 text-left"
        >
          <div className="flex items-center gap-6">
            <span className="flex items-center gap-1.5 text-xs text-gray-500">
              <Wallet size={13} className="text-brand-700" />
              <span className="font-semibold text-gray-800">{money(todaySales)}</span>
              <span className="text-gray-400">today</span>
            </span>
            <span className="flex items-center gap-1.5 text-xs text-gray-500">
              <Receipt size={13} className="text-brand-700" />
              <span className="font-semibold text-gray-800">{sales.length}</span>
              <span className="text-gray-400">sales</span>
            </span>
            <span className="flex items-center gap-1.5 text-xs text-gray-500">
              <PackageCheck size={13} className="text-amber-500" />
              <span className="font-semibold text-gray-800">{itemsSold}</span>
              <span className="text-gray-400">items</span>
            </span>
            {lowStock > 0 && (
              <span className="flex items-center gap-1.5 text-xs">
                <AlertTriangle size={13} className="text-red-500" />
                <span className="font-semibold text-red-600">{lowStock} low stock</span>
              </span>
            )}
          </div>
          <span className="text-gray-400">
            {statsOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </span>
        </button>

        {/* Expanded detail */}
        {statsOpen && (
          <div className="grid grid-cols-2 gap-3 border-t border-gray-100 p-4 sm:grid-cols-4">
            {[
              { icon: Wallet,        label: "Today's sales",  value: money(todaySales), color: "text-brand-700",  bg: "bg-brand-50"  },
              { icon: Receipt,       label: "Transactions",   value: sales.length,      color: "text-brand-700",  bg: "bg-brand-50"  },
              { icon: PackageCheck,  label: "Items sold",     value: itemsSold,         color: "text-amber-600",  bg: "bg-amber-50"  },
              { icon: AlertTriangle, label: "Low stock",      value: lowStock,          color: "text-red-600",    bg: "bg-red-50"    },
            ].map(({ icon: Icon, label, value, color, bg }) => (
              <div key={label} className={`flex items-center gap-3 rounded-xl ${bg} px-3 py-2.5`}>
                <Icon size={16} className={color} />
                <div>
                  <p className="text-[10px] font-medium text-gray-400">{label}</p>
                  <p className={`text-base font-extrabold ${color}`}>{value}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Search + Categories ── */}
      <div className="shrink-0 space-y-2 border-b border-gray-100 bg-white px-4 py-3">
        <div className="relative">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" size={15} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search or scan barcode…"
            className="w-full rounded-xl border-0 bg-gray-50 py-2.5 pl-10 pr-4 text-sm ring-1 ring-black/5 focus:bg-white focus:outline-2 focus:outline-brand-700"
          />
        </div>
        <div className="flex gap-1.5 overflow-x-auto pb-0.5 scrollbar-none">
          {categories.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`whitespace-nowrap rounded-full px-3.5 py-1 text-xs font-semibold transition ${
                category === c
                  ? "bg-brand-700 text-white"
                  : "bg-gray-100 text-gray-500 hover:bg-brand-50 hover:text-brand-700"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* ── Product grid ── */}
      <div className="flex-1 overflow-y-auto p-3">
        <div className="grid auto-rows-min grid-cols-2 gap-2.5 pb-4 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((p) => (
            <ProductCard key={p.id} product={p} inCart={cart.find((i) => i.id === p.id)?.qty ?? 0} onAdd={onAdd} />
          ))}
          {filtered.length === 0 && (
            <div className="col-span-full flex flex-col items-center gap-2 py-20 text-center">
              <p className="text-sm font-semibold text-gray-500">No products found</p>
              <p className="text-xs text-gray-400">Try a different search or category.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
