import { useLanguage } from "@/lib/i18n"
import type { LucideIcon } from "lucide-react"
import { CircleCheckIcon, TriangleAlertIcon } from "lucide-react"

import { useAccounts } from "@/api/accounts"
import { useSettings } from "@/api/misc"
import type { ProxiesResponse } from "@/api/types"
import { toneText, type Tone } from "@/components/status"
import { useAccountsView } from "@/features/accounts/accounts-view"
import { cn } from "@/lib/utils"

import { accountsInRun, proxyCapacity, type CapacityKind } from "./capacity"
import { capacityText } from "./labels"

/* Строка о том, хватит ли прокси на «Потоки» из настроек. proxy_pool раздаёт
   наименее занятый и не мешает нескольким делам идти через один адрес: при
   потоках больше, чем живых прокси, аккаунты сядут на чужой IP. Аккаунтов
   берём столько же, сколько возьмёт запуск кампании, — сказать нечего, когда
   их нет вовсе. */

const ICON: Record<CapacityKind, LucideIcon> = {
  off: TriangleAlertIcon,
  empty: TriangleAlertIcon,
  none: TriangleAlertIcon,
  short: TriangleAlertIcon,
  ok: CircleCheckIcon,
}

const TONE: Record<CapacityKind, Tone> = {
  off: "warn",
  empty: "warn",
  none: "bad",
  short: "warn",
  ok: "ok",
}

export function ProxyCapacity({ data }: { data: ProxiesResponse }) {
  useLanguage()
  const settings = useSettings()
  const accounts = useAccounts()
  const selected = useAccountsView((s) => s.selected)
  if (!settings.data || !accounts.data) return null
  const total = accountsInRun(accounts.data.accounts, selected)
  const cap = proxyCapacity(data, settings.data.threads, total)
  if (!cap) return null
  const Icon = ICON[cap.kind]
  return (
    <div className="flex items-center gap-2 rounded-xl border bg-card px-3 py-3 text-sm">
      <Icon className={cn("size-4 shrink-0", toneText[TONE[cap.kind]])} />
      <span className="min-w-0">{capacityText(cap)}</span>
    </div>
  )
}
