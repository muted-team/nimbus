import { t, useLanguage } from "@/lib/i18n"
import { Progress } from "@/components/ui/progress"
import { fmtInt } from "@/lib/format"
import { cn } from "@/lib/utils"

/* Ход загрузки файлов: «Загрузка 12 из 40 — не закрывайте страницу» и
   полоса. Прилипает к верху прокрутки — на телефоне видна, где бы ни был. */
export function UploadStatus({ done, total, className }: { done: number; total: number; className?: string }) {
  useLanguage()
  return (
    <div
      role="status"
      className={cn(
        "sticky top-2 z-20 flex flex-col gap-2 rounded-md border border-info/40 bg-card p-3 text-sm shadow-sm",
        className
      )}
    >
      <span>{t("Загрузка")}{fmtInt(done)}{t("из")}{fmtInt(total)}{t("— не закрывайте страницу")}</span>
      <Progress value={total ? (done / total) * 100 : 0} />
    </div>
  )
}
