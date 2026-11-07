import { useLanguage } from "@/lib/i18n"
import { useMemo } from "react"
import { PlayIcon, TriangleAlertIcon } from "lucide-react"
import { useLocation } from "wouter"

import { useAccounts } from "@/api/accounts"
import { useProxies } from "@/api/proxies"
import { sectionPath } from "@/app/sections"
import { Hint } from "@/components/hint"
import { Panel } from "@/components/panel"
import { Button } from "@/components/ui/button"
import { Alert, AlertTitle } from "@/components/ui/alert"
import { Spinner } from "@/components/ui/spinner"
import { useAccountsView } from "@/features/accounts/accounts-view"
import { inShadow } from "@/features/accounts/filter"
import { healthCounts, usableProxies } from "@/features/proxies/health"
import { cn } from "@/lib/utils"

import { checkForm, firstErrorText } from "./form-model"
import { useFormStore } from "./form-store"
import { CONFIRM_LABEL, LAUNCH_LABEL, SHORTAGE_LABEL, SUMMARY_LABEL } from "./labels"
import { launchSummary } from "./launch-summary"
import { useCampaignLauncher } from "./launcher"
import { findShortage } from "./shortage"
import { useSlotFiles } from "./slot-files"

/* Сводка перед запуском — закреплена справа от формы: что уйдёт, сколько
   постов, хватит ли файлов, что требует внимания. Она и есть подтверждение:
   запуск отсюда уходит без окна-простыни, всё сказано рядом с кнопкой.
   Строки — те же, что в окне подтверждения при запуске с других экранов
   (launch-summary.ts), чтобы одно и то же не называлось по-разному. */

export function LaunchPanel() {
  const language = useLanguage()
  const [, navigate] = useLocation()
  const values = useFormStore((s) => s.values)
  const accounts = useAccounts().data?.accounts
  const proxies = useProxies().data
  const info = useSlotFiles()
  const { launch, busy, live } = useCampaignLauncher()

  const total = accounts?.length
  const noLogin = accounts?.filter((a) => !a.has_session).length ?? 0
  const shadow = accounts?.filter(inShadow).length ?? 0
  const counts = proxies ? healthCounts(proxies.health) : null
  const deadProxies = !!proxies && proxies.enabled && proxies.proxies.length > 0 && usableProxies(counts!) === 0

  const summary = useMemo(() => {
    void language
    if (!values) return null
    const { errors, parsed } = checkForm(values)
    if (!parsed) return { error: firstErrorText(errors, values.media), rows: [] as [string, string][], warn: new Set<string>() }
    const short = findShortage(values, info, total)
    const { details } = launchSummary(values, parsed, { total }, short)
    // строки нехватки файлов — жёлтым: их подпись — имя папки-слота
    const warn = new Set(short.map((s) => SHORTAGE_LABEL.folder(values.media, s.index)))
    // «Постов на аккаунт» в сводке — внутри строки «аккаунты × посты = всего»
    const rows = total ? details.filter(([label]) => label !== CONFIRM_LABEL.posts) : details
    return { error: null, rows, warn, posts: parsed.posts }
  }, [values, info, total, language])

  const openAccounts = (filter: "nologin" | "shadow") => {
    useAccountsView.getState().setFilter(filter)
    navigate(sectionPath("accounts"))
  }

  return (
    <Panel title={SUMMARY_LABEL.title} className="border-primary/20" bodyClassName="gap-5">
      {summary?.error ? (
        <Alert variant="destructive">
          <TriangleAlertIcon />
          <AlertTitle>{summary.error}</AlertTitle>
        </Alert>
      ) : null}
      {summary?.rows.length ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm [&_dd]:text-balance">
          {summary.rows.map(([label, value]) => {
            return (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className={cn("text-right tabular", summary.warn.has(label) && "text-warning")}>{value}</dd>
              </div>
            )
          })}
          {total !== undefined && summary.posts ? (
            <div className="contents">
              <dt className="text-muted-foreground">{SUMMARY_LABEL.posts}</dt>
              <dd className="text-right tabular">{SUMMARY_LABEL.postsValue(total, summary.posts)}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}

      {noLogin || shadow || deadProxies ? (
        <div className="flex flex-col gap-1 border-t pt-3 text-sm">
          <span className="text-xs text-muted-foreground">{SUMMARY_LABEL.attention}</span>
          {noLogin ? <AttentionLink onClick={() => openAccounts("nologin")}>{SUMMARY_LABEL.noLogin(noLogin)}</AttentionLink> : null}
          {shadow ? <AttentionLink onClick={() => openAccounts("shadow")}>{SUMMARY_LABEL.shadow(shadow)}</AttentionLink> : null}
          {deadProxies ? (
            <AttentionLink onClick={() => navigate(sectionPath("proxies"))}>{SUMMARY_LABEL.deadProxies}</AttentionLink>
          ) : null}
        </div>
      ) : null}

      {/* Одна кнопка запуска — после сводки и на компьютере, и на телефоне. */}
      <Hint label={LAUNCH_LABEL.start} hotkey="Mod+Enter" reason={live ? SUMMARY_LABEL.running : undefined} className="w-full">
        <Button
          className="h-11 w-full"
          disabled={busy || live}
          onClick={() => void launch(undefined, { confirm: false })}
        >
          {busy ? <Spinner data-icon="inline-start" /> : <PlayIcon data-icon="inline-start" />}
          {busy ? LAUNCH_LABEL.starting : LAUNCH_LABEL.start}
        </Button>
      </Hint>
    </Panel>
  )
}

function AttentionLink({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  useLanguage()
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 self-start rounded-sm text-warning outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <TriangleAlertIcon className="size-3.5" />
      {children}
    </button>
  )
}
