import { t, useLanguage } from "@/lib/i18n"
import { userMessage } from "@/api/client"
import { CircleAlertIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"

/** сколько непринятых строк показывать, остальные — одной строкой «и ещё N» */
const REJECTED_SHOWN = 8

/** Строки, которые сервер не смог разобрать: номер строки и причина. */
export function RejectedLines({ errors }: { errors: { line: number; error: string }[] }) {
  useLanguage()
  const shown = errors.slice(0, REJECTED_SHOWN)
  return (
    <Alert variant="destructive">
      <CircleAlertIcon />
      <AlertTitle>{t("Не принято строк:")}{errors.length}</AlertTitle>
      <AlertDescription>
        <div className="flex flex-col gap-1">
          {shown.map((e) => (
            <div key={e.line} className="flex gap-3 text-sm text-muted-foreground">
              <span className="shrink-0 tabular whitespace-nowrap">{t("строка")}{e.line}</span>
              <span className="min-w-0 break-words">{userMessage(e.error)}</span>
            </div>
          ))}
          {errors.length > REJECTED_SHOWN ? (
            <div className="text-sm text-muted-foreground">{t("и ещё")}{errors.length - REJECTED_SHOWN}</div>
          ) : null}
        </div>
      </AlertDescription>
    </Alert>
  )
}
