import { STORE } from "../config";

const navItems = [
  { id: "terminal", label: "Terminal", icon: "bi-upc-scan" },
];

export default function Sidebar({ page, setPage, user, onLogout }) {
  return (
    <>
      {/* Desktop sidebar — icon only */}
      <aside className="hidden w-48 shrink-0 flex-col bg-gradient-to-b from-brand-950 to-brand-900 py-4 lg:flex">
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 mb-6">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-brand-950">
            <i className="bi bi-shop text-lg" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-extrabold text-white">
              {STORE.name.replace("Mart", "")}<span className="text-mint">Mart</span>
            </p>
            <p className="text-[10px] text-white/40">{STORE.tagline}</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex flex-1 flex-col gap-0.5 px-3 pt-2">
          {navItems.map(({ id, label, icon }) => {
            const active = page === id;
            return (
              <button
                key={id}
                onClick={() => setPage(id)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition ${
                  active ? "bg-white/15 text-white" : "text-white/50 hover:bg-white/10 hover:text-white"
                }`}
              >
                <i className={`bi ${icon} text-base ${active ? "text-accent" : ""}`} />
                {label}
              </button>
            );
          })}
        </nav>

        {/* User + logout */}
        <div className="mx-3 rounded-2xl bg-white/8 p-3 ring-1 ring-white/10">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-mint font-bold text-brand-950 text-sm">
              {user.name[0]}
            </div>
            <div className="min-w-0">
              <p className="truncate text-xs font-semibold text-white">{user.name}</p>
              <p className="text-[10px] text-white/40 capitalize">{user.role}</p>
            </div>
          </div>
          <button
            onClick={onLogout}
            className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/15 py-1.5 text-xs font-medium text-white/60 hover:bg-white/10 transition"
          >
            <i className="bi bi-box-arrow-right" /> Log out
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="fixed top-0 left-0 right-0 z-20 flex items-center justify-between border-b border-gray-100 bg-white px-4 py-3 shadow-sm lg:hidden">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-brand-950">
            <i className="bi bi-shop text-sm" />
          </div>
          <p className="text-sm font-extrabold text-brand-950">
            {STORE.name.replace("Mart", "")}<span className="text-mint">Mart</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={onLogout} className="text-xs font-semibold text-gray-400 hover:text-red-500 transition">
            Log out
          </button>
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-700 font-bold text-white text-xs">
            {user.name[0]}
          </div>
        </div>
      </div>

      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 right-0 z-20 flex border-t border-gray-200 bg-white lg:hidden">
        {navItems.map(({ id, label, icon }) => {
          const active = page === id;
          return (
            <button
              key={id}
              onClick={() => setPage(id)}
              className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-semibold transition ${
                active ? "text-brand-700" : "text-gray-400"
              }`}
            >
              <i className={`bi ${icon} text-lg`} />
              {label}
            </button>
          );
        })}
      </nav>
    </>
  );
}
