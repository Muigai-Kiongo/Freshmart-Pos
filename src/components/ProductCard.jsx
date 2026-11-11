import { money } from "../utils";

export default function ProductCard({ product, inCart, onAdd }) {
  const out   = product.stock === 0;
  const low   = !out && product.stock < 10;
  const maxed = inCart >= product.stock;

  return (
    <button
      onClick={() => onAdd(product)}
      disabled={out || maxed}
      className="group relative flex flex-col rounded-2xl bg-white text-left shadow-sm ring-1 ring-black/5 transition hover:shadow-md hover:ring-brand-700/30 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {/* Cart badge */}
      {inCart > 0 && (
        <span className="absolute right-2 top-2 z-10 flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-700 px-1.5 text-[10px] font-bold text-white shadow">
          {inCart}
        </span>
      )}

      {/* Icon area */}
      <div className="flex h-24 items-center justify-center rounded-t-2xl bg-gradient-to-br from-brand-50 to-brand-100">
        {product.image
          ? <img src={product.image} alt={product.name} className="h-full w-full rounded-t-2xl object-cover" />
          : <i className={`bi ${product.icon} text-5xl text-brand-700`} />
        }
      </div>

      {/* Info */}
      <div className="flex flex-1 flex-col px-3 py-2.5">
        <p className="line-clamp-2 text-xs font-semibold leading-snug text-gray-800">{product.name}</p>

        <div className="mt-auto flex items-end justify-between pt-2">
          <div>
            <p className="text-sm font-extrabold text-brand-700">{money(product.price)}</p>
            <p className={`text-[10px] font-medium ${out ? "text-red-500" : low ? "text-amber-500" : "text-gray-400"}`}>
              {out ? "Out of stock" : low ? `Only ${product.stock} left` : `${product.stock} in stock`}
            </p>
          </div>
          {!out && !maxed && (
            <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-brand-700 text-white transition group-hover:bg-brand-800">
              <i className="bi bi-plus-lg text-sm" />
            </span>
          )}
          {maxed && !out && (
            <span className="rounded-lg bg-brand-100 px-2 py-0.5 text-[10px] font-bold text-brand-700">Max</span>
          )}
        </div>
      </div>
    </button>
  );
}
