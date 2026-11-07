import { useLanguage } from "@/lib/i18n"
import { CopyIcon } from "lucide-react"

import type { LogItem } from "@/api/types"
import { userMessage } from "@/api/client"
import { IconButton } from "@/components/hint"
import { StatusDot } from "@/components/status"
import { atUsername } from "@/features/accounts/username"
import { fmtClock } from "@/lib/format"
import { copyWithToast } from "@/lib/native"
import { cn } from "@/lib/utils"

import { LEVEL_TONE, LOGS_LABEL, LOGS_TOAST, ROW_MARK_CLASS, rowMark } from "./labels"

/* Строка журнала — общая для раздела «Журнал», журнала прогона и карточки
   аккаунта. Юзернейм — с собакой, как везде; нажатие по нему — журнал этого
   аккаунта (onAccount). «Скопировать» — строкой целиком: время, аккаунт,
   текст. Кнопка видна при наведении, на телефоне — всегда. */

const logLine = (item: LogItem) =>
  [fmtClock(item.ts), item.account ? atUsername(item.account) : "", item.debug ? item.text : userMessage(item.text)].filter(Boolean).join(" ")

export function LogRow({
  item,
  onAccount,
  hideAccount,
}: {
  item: LogItem
  onAccount?: (account: string) => void
  /** в карточке аккаунта его имя в каждой строке — повтор */
  hideAccount?: boolean
}) {
  useLanguage()
  const mark = rowMark(item)
  const account = item.account
  return (
    <div className="group/log relative flex items-baseline gap-3 px-4 py-2 text-row md:px-6 select-text pointer-coarse:pr-12">
      <span className="tabular shrink-0 text-xs text-muted-foreground">{fmtClock(item.ts)}</span>
      <StatusDot tone={LEVEL_TONE[item.level]} />
      {account && !hideAccount ? (
        onAccount ? (
          <button
            type="button"
            onClick={() => onAccount(account)}
            className="max-w-32 shrink-0 truncate rounded-sm text-xs text-muted-foreground outline-none hover:text-foreground hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {atUsername(account)}
          </button>
        ) : (
          <span className="max-w-32 shrink-0 truncate text-xs text-muted-foreground">{atUsername(account)}</span>
        )
      ) : null}
      {mark ? <span className={ROW_MARK_CLASS[mark.kind]}>{mark.text}</span> : null}
      <span className={cn("min-w-0 flex-1 break-words", item.debug && "text-muted-foreground")}>{item.debug ? item.text : userMessage(item.text)}</span>
      <IconButton
        label={LOGS_LABEL.copy}
        icon={CopyIcon}
        size="icon-xs"
        className="absolute top-1/2 right-2 -translate-y-1/2 bg-background text-muted-foreground opacity-0 group-hover/log:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
        onClick={() => void copyWithToast(logLine(item), LOGS_TOAST.copied)}
      />
    </div>
  )
}
