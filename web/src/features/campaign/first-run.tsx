import { useLanguage } from "@/lib/i18n"
import { CheckIcon } from "lucide-react"
import { Link } from "wouter"

import { useAccounts } from "@/api/accounts"
import { useCampaignStatus } from "@/api/campaign"
import { useMediaLibrary } from "@/api/misc"
import { useProxies } from "@/api/proxies"
import { sectionPath } from "@/app/sections"
import { Panel } from "@/components/panel"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

import { activeSlots } from "./form-model"
import { useFormStore } from "./form-store"
import { CHECKLIST_LABEL } from "./labels"

/* Чек-лист первого запуска: пустая программа учит по одному шагу за раз —
   аккаунты, прокси, креативы, запуск. Сделанный шаг отмечается галочкой,
   следующий — кнопкой. Когда первые три готовы, чек-лист уходит: дальше
   всё видно на самом экране. Пока ответов с сервера нет, его не
   показываем, чтобы он не мигал у настроенной программы. */

export function FirstRun() {
  useLanguage()
  const accounts = useAccounts().data
  const proxies = useProxies().data
  const library = useMediaLibrary().data
  const values = useFormStore((s) => s.values)
  const { data: st } = useCampaignStatus()
  if (!accounts || !proxies || !library || !values) return null

  const hasMedia = activeSlots(values).length > 0 || library.folders.some((f) => f.photos + f.videos > 0)
  const steps = [
    { done: accounts.accounts.length > 0, label: CHECKLIST_LABEL.accounts, to: sectionPath("accounts") },
    { done: proxies.proxies.length > 0, label: CHECKLIST_LABEL.proxies, to: sectionPath("proxies") },
    { done: hasMedia, label: CHECKLIST_LABEL.media, to: sectionPath("media") },
    { done: !!st && st.status !== "idle", label: CHECKLIST_LABEL.launch, to: null },
  ]
  if (steps.slice(0, 3).every((s) => s.done)) return null
  const next = steps.findIndex((s) => !s.done)

  return (
    <Panel title={CHECKLIST_LABEL.title}>
      <ol className="flex flex-col gap-1">
        {steps.map((s, i) => (
          <li key={s.label} className="flex h-10 items-center gap-3">
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs tabular",
                s.done ? "border-transparent bg-success/15 text-success" : "text-muted-foreground",
                i === next && "border-foreground text-foreground"
              )}
            >
              {s.done ? <CheckIcon className="size-3.5" /> : i + 1}
            </span>
            <span className={cn("min-w-0 flex-1 text-sm", s.done && "text-muted-foreground line-through")}>{s.label}</span>
            {i === next && s.to ? (
              <Button variant="outline" size="sm" nativeButton={false} render={<Link href={s.to} />}>
                {CHECKLIST_LABEL.open}
              </Button>
            ) : null}
          </li>
        ))}
      </ol>
    </Panel>
  )
}
