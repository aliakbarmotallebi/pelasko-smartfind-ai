import type { ProductData } from "../types";

interface ProductCardProps {
  product: ProductData;
}

function formatPrice(price: number): string {
  return new Intl.NumberFormat("fa-IR").format(price);
}

export default function ProductCard({ product }: ProductCardProps) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-700 bg-slate-900/80">
      <div className="flex gap-3 p-3">
        {product.image ? (
          <img
            src={product.image}
            alt={product.name}
            className="h-20 w-20 shrink-0 rounded-xl object-cover"
          />
        ) : (
          <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-xl bg-slate-800 text-xs text-slate-400">
            بدون تصویر
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-white">{product.name}</h3>
          <p className="mt-1 text-sm font-medium text-emerald-400">
            {formatPrice(product.price)} تومان
          </p>
          {product.colors.length > 0 && (
            <p className="mt-1 text-xs text-slate-400">
              رنگ‌ها: {product.colors.join("، ")}
            </p>
          )}
          {product.specs.length > 0 && (
            <p className="mt-1 line-clamp-2 text-xs text-slate-400">
              {product.specs.slice(0, 2).join(" | ")}
            </p>
          )}
          <div className="mt-2 flex items-center gap-2">
            <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300">
              امتیاز: {product.score.toFixed(2)}
            </span>
            {product.link && (
              <a
                href={product.link}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-medium text-sky-400 hover:text-sky-300"
              >
                مشاهده محصول
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
