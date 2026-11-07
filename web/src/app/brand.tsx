import { cn } from "@/lib/utils"

/* Имя и знак продукта — одно место на весь интерфейс (как modules/brand.py у
   сервера). Знак свой: облако (Nimbus) с «плеем» на индиго. Чужой товарный
   знак в логотипе делал программу похожей на неофициальный клон.
   Рисунок один — web/public/favicon.svg: его же показывает вкладка браузера,
   и из него собирается иконка exe (dev/_render_icon.py). */

export const PRODUCT = "Nimbus"

export function BrandMark({ className }: { className?: string }) {
  return (
    <img
      src="/favicon.svg"
      alt=""
      width={32}
      height={32}
      className={cn("size-8 shrink-0 rounded-lg", className)}
      aria-hidden
    />
  )
}
