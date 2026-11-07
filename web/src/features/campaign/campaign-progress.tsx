import { t, useLanguage } from "@/lib/i18n"
import { useMemo } from "react"

import { useCampaignStatus } from "@/api/campaign"
import { userMessage } from "@/api/client"
import { useLogs } from "@/api/logs"
import type { CampaignStatus } from "@/api/types"
import { StatusBadge, Stat } from "@/components/status"
import { Progress } from "@/components/ui/progress"
import { atUsername } from "@/features/accounts/username"
import { logKey } from "@/features/logs/log-filter"
import { LogRow } from "@/features/logs/log-row"
import { useNow } from "@/hooks/use-now"
import { fmtDateTime, fmtInt, fmtSpan, fmtUntil } from "@/lib/format"

import { OUTCOME_LABEL, PROGRESS_LABEL, RUN_LABEL, STATE_LABEL, stepLabel, type ReportOutcome } from "./labels"

/* Прогон как развёртывание: статус, ряд крупных чисел, полоса по постам,
   воркеры списком и журнал только этого прогона. Полоса считается по постам,
   а не по аккаунтам: при одном аккаунте и десяти постах она стояла бы на
   нуле до самого конца. */

/** Сколько осталось по нынешней скорости; null — считать ещё не по чему. */
function estimateLeft(st: CampaignStatus, now: number): number | null {
  if (st.status !== "running" || !st.started_at || !st.posts_done) return null
  const spent = now - new Date(st.started_at).getTime()
  const left = st.posts_total - st.posts_done
  if (!(spent > 0) || left <= 0) return null
  return (spent / st.posts_done) * left
}

export function CampaignProgress() {
  useLanguage()
  const { data: st } = useCampaignStatus()
  // отсчёт до круга и «осталось» идут сами, без нового снимка с сервера
  const now = useNow(1000, st?.status === "waiting" || st?.status === "running")
  if (!st || st.status === "idle") return null

  const state = STATE_LABEL[st.status]
  const pct = st.posts_total
    ? Math.round((st.posts_done / st.posts_total) * 100)
    : st.status === "stopped"
      ? 100
      : 0
  // без ?? 0 снимок стенда (и старого сервера), где поля removed нет, ронял бы
  // весь экран публикации на чтении .length
  const report = (Object.keys(OUTCOME_LABEL) as ReportOutcome[])
    .map((key) => ({ key, n: st.report[key]?.length ?? 0 }))
    .filter((r) => r.n > 0)
  const left = estimateLeft(st, now)

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted-foreground">
        <StatusBadge tone={state.tone} icon={state.icon} spin={state.spin}>
          {state.text}
        </StatusBadge>
        {st.repeat && st.round ? (
          <span className="tabular">
            {PROGRESS_LABEL.round} {fmtInt(st.round)}
          </span>
        ) : null}
        {st.status === "waiting" && st.next_run_at ? (
          <span className="tabular">
            {PROGRESS_LABEL.nextRound} — {fmtUntil(st.next_run_at, now)}
          </span>
        ) : null}
        {st.started_at ? (
          <span className="tabular">
            {PROGRESS_LABEL.started} {fmtDateTime(st.started_at)}
          </span>
        ) : null}
        {/* «Конец» — только у остановленного прохода: во время ожидания круга
            это конец прошлого круга, а не всей публикации */}
        {st.status !== "waiting" && st.finished_at ? (
          <span className="tabular">
            {PROGRESS_LABEL.finished} {fmtDateTime(st.finished_at)}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label={RUN_LABEL.posts}
          value={`${fmtInt(st.posts_done)} / ${fmtInt(st.posts_total)}`}
          sub={`${pct} %`}
        />
        <Stat label={RUN_LABEL.left} value={left === null ? "—" : `≈ ${fmtSpan(left)}`} />
        <Stat label={RUN_LABEL.accounts} value={`${fmtInt(st.accounts_done)} / ${fmtInt(st.accounts_total)}`} />
        <Stat label={RUN_LABEL.failed} value={fmtInt(st.posts_failed)} />
      </div>
      <Progress value={pct} aria-label={PROGRESS_LABEL.posts} />

      {report.length || st.stop_reason ? (
        <div className="flex flex-wrap items-center gap-2">
          {report.map((r) => (
            <StatusBadge key={r.key} tone={OUTCOME_LABEL[r.key].tone}>
              {OUTCOME_LABEL[r.key].label(r.n)}
            </StatusBadge>
          ))}
          {st.stop_reason ? <span className="text-sm text-muted-foreground select-text">{userMessage(st.stop_reason)}</span> : null}
        </div>
      ) : null}

      {st.workers.length ? (
        <div className="flex flex-col">
          <h3 className="pb-2 text-xs text-muted-foreground">{RUN_LABEL.workers}</h3>
          <ul className="overflow-hidden rounded-xl border">
            {st.workers.map((w) => (
              <li key={w.account} className="flex h-10 items-center gap-3 border-b px-4 text-row last:border-0">
                <span className="min-w-0 flex-1 truncate font-medium">{atUsername(w.account)}</span>
                <span className="shrink-0 text-muted-foreground">
                  {stepLabel(w.step)}
                  {w.step === "publishing" ? t(" · пост {0}", [fmtInt(w.posts_done + 1)]) : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <RunLog since={st.started_at} />
    </section>
  )
}

const RUN_LOG_LIMIT = 30

/* Журнал только этого прогона: записи с его начала, без подробностей,
   свежие сверху. Весь журнал — в своём разделе. */
function RunLog({ since }: { since: string | null }) {
  useLanguage()
  const events = useLogs((s) => s.events)
  const from = since ? new Date(since).getTime() / 1000 : null
  const items = useMemo(
    () => (from === null ? [] : events.filter((e) => !e.debug && e.ts >= from)),
    [events, from]
  )
  if (from === null) return null
  return (
    <div className="flex flex-col">
      <h3 className="pb-2 text-xs text-muted-foreground">{RUN_LABEL.log}</h3>
      <div className="max-h-72 overflow-y-auto rounded-xl border">
        {items.length ? (
          <>
            {items.slice(0, RUN_LOG_LIMIT).map((item, i) => (
              <LogRow key={logKey(item, i)} item={item} />
            ))}
            {items.length > RUN_LOG_LIMIT ? (
              <p className="px-4 py-2 text-xs text-muted-foreground">{RUN_LABEL.more(items.length - RUN_LOG_LIMIT)}</p>
            ) : null}
          </>
        ) : (
          <p className="px-4 py-3 text-sm text-muted-foreground">{RUN_LABEL.logEmpty}</p>
        )}
      </div>
    </div>
  )
}
