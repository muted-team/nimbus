import { localize, t, useLanguage } from "@/lib/i18n"
import { userMessage } from "@/api/client"
import { useMemo, useRef, useState } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { CircleAlertIcon, HistoryIcon, ListChecksIcon, RotateCcwIcon } from "lucide-react"

import { useCampaignStatus } from "@/api/campaign"
import type { CampaignResult } from "@/api/types"
import { FilterChips, type FilterChip } from "@/components/filter-chips"
import { Panel } from "@/components/panel"
import { StatusBadge } from "@/components/status"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { atUsername } from "@/features/accounts/username"
import { count, fmtInt } from "@/lib/format"

import { useCampaignLauncher } from "./launcher"
import { copyReport, groupReasons, isRestoredReport, outcomeOf } from "./report"
import { RESULTS_LABEL, RESULT_LABEL, RESTORED_TEXT, type ResultOutcome } from "./labels"

/* Итог по аккаунтам после кампании: сколько опубликовано и почему нет.
   Пустой список — панель не показываем вовсе. Над списком — срезы по исходу
   и причины неудач одной строкой, сгруппированные: «пост отклонён ×3 ·
   капча ×1» читается быстрее, чем тридцать строк с одним и тем же. Строкой
   выше — сколько постов TikTok снял за нарушение правил и пометка, если
   отчёт поднят с диска после перезапуска. Список виртуализован: на тысяче
   аккаунтов он не тормозит экран. */

type ResultsFilter = "all" | ResultOutcome

export function CampaignResults() {
  useLanguage()
  const { data: st } = useCampaignStatus()
  const { launch, busy, live } = useCampaignLauncher()
  const [filter, setFilter] = useState<ResultsFilter>("all")
  const results = useMemo(() => st?.results ?? [], [st?.results])
  const ppa = st?.posts_per_account ?? 0

  const outcomes = useMemo(() => results.map((r) => outcomeOf(r, ppa)), [results, ppa])
  const reasons = useMemo(() => groupReasons(results, ppa), [results, ppa])
  const shown = useMemo(
    () => (filter === "all" ? results : results.filter((_, i) => outcomes[i] === filter)),
    [results, outcomes, filter]
  )

  if (!st || !results.length) return null

  const removed = st.report.posts_removed ?? 0
  // отчёт поднят с диска после перезапуска: карточка должна сказать, что это
  // прошлый запуск, иначе человек примет его за только что законченный проход
  const restored = isRestoredReport(st)
  // повтор — по тем, кто не дал ни одного поста и не забанен: у забаненного
  // повторять нечего, а частично опубликованные своё уже получили
  const stuck = results.filter((r) => !r.banned && !r.posts_done).map((r) => r.account)

  const chips: FilterChip<ResultsFilter>[] = localize([
    { value: "all", label: "Все", count: results.length },
    ...(Object.keys(RESULT_LABEL) as ResultOutcome[]).map((key) => ({
      value: key,
      label: RESULT_LABEL[key].text,
      count: outcomes.filter((o) => o === key).length,
      tone: RESULT_LABEL[key].tone,
      hideEmpty: true,
    })),
  ])

  return (
    <Panel
      title={RESULTS_LABEL.title}
      meta={<span className="text-sm font-normal text-muted-foreground">{count(results.length, [t("аккаунт"), t("аккаунта"), t("аккаунтов")])}</span>}
      flush
      actions={
        // Panel не переносит и не сжимает блок действий целиком — слово
        // прячем до sm, число остаётся всегда: по нему понятно, сколько
        // повторится, а слово — в aria-label кнопки
        <>
          <Button variant="outline" size="sm" aria-label={RESULTS_LABEL.copy} onClick={() => void copyReport(st)}>
            <ListChecksIcon />
            <span className="hidden sm:inline">{RESULTS_LABEL.copy}</span>
          </Button>
          {stuck.length ? (
            <Button
              variant="outline"
              size="sm"
              disabled={live || busy}
              aria-label={RESULTS_LABEL.retry(stuck.length)}
              onClick={() => void launch(stuck)}
            >
              {busy ? <Spinner /> : <RotateCcwIcon />}
              <span className="hidden sm:inline">{RESULTS_LABEL.retryWord} </span>({fmtInt(stuck.length)})
            </Button>
          ) : null}
        </>
      }
    >
      {restored ? (
        <div className="flex items-center gap-2 border-b bg-muted/50 px-4 py-2 text-xs text-muted-foreground">
          <HistoryIcon className="size-3.5 shrink-0" />
          <span className="min-w-0">{t(RESTORED_TEXT)}</span>
        </div>
      ) : null}
      {removed ? (
        <div className="flex items-center gap-2 border-b bg-destructive/10 px-4 py-2 text-xs text-destructive">
          <CircleAlertIcon className="size-3.5 shrink-0" />
          <span className="min-w-0">{RESULTS_LABEL.removed(removed)}</span>
        </div>
      ) : null}
      <div className="flex flex-col gap-2 border-b px-4 py-3">
        <FilterChips items={chips} value={filter} onValueChange={setFilter} label={RESULTS_LABEL.title} />
        {reasons.length ? (
          <p className="text-xs text-muted-foreground select-text">
            {reasons.map(([reason, n]) => `${reason} ×${fmtInt(n)}`).join(" · ")}
          </p>
        ) : null}
      </div>
      <ResultList results={shown} ppa={ppa} />
    </Panel>
  )
}

const ROW_H = 40

function ResultList({ results, ppa }: { results: CampaignResult[]; ppa: number }) {
  useLanguage()
  const scrollRef = useRef<HTMLDivElement>(null)
  // виртуализатор отдаёт изменяемые функции — правило предупреждает компилятор
  // React, которого в сборке нет; других способов пользоваться им нет
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: results.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  })
  return (
    <div ref={scrollRef} className="max-h-[32rem] overflow-y-auto">
      <ul className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((row) => {
          const r = results[row.index]
          const outcome = outcomeOf(r, ppa)
          return (
            <li
              key={r.account}
              data-index={row.index}
              ref={virtualizer.measureElement}
              className="absolute top-0 left-0 flex min-h-10 w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b px-4 py-2 text-row"
              style={{ transform: `translateY(${row.start}px)` }}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium select-text">{atUsername(r.account)}</div>
                {r.reason ? <div className="truncate text-xs text-muted-foreground select-text">{userMessage(r.reason)}</div> : null}
              </div>
              {/* когда не помещается рядом с именем — переносится своей строкой,
                  ml-auto прижимает её к правому краю и там, и тут */}
              <div className="ml-auto flex flex-wrap items-center justify-end gap-3">
                {r.posts_done ? (
                  <span className="tabular text-muted-foreground">
                    {fmtInt(r.posts_done)}
                    {outcome === "partial" ? t(" из {0}", [fmtInt(ppa)]) : ""}
                  </span>
                ) : null}
                <StatusBadge tone={RESULT_LABEL[outcome].tone}>{RESULT_LABEL[outcome].text}</StatusBadge>
                {r.removed ? (
                  <span className="inline-flex items-center gap-1 text-xs text-destructive" title={RESULTS_LABEL.removed(r.removed)}>
                    <CircleAlertIcon className="size-3.5" aria-label={RESULTS_LABEL.removed(r.removed)} />
                    <span className="tabular">{fmtInt(r.removed)}</span>
                  </span>
                ) : null}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
