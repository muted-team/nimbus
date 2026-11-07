import { useLanguage } from "@/lib/i18n"
import { useEffect, useLayoutEffect, useMemo, useRef } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { ScrollTextIcon, SearchXIcon, Trash2Icon, XIcon } from "lucide-react"

import { clearLogs, useLogs } from "@/api/logs"
import { sectionTitle } from "@/app/sections"
import { confirmDestructive } from "@/components/confirm"
import { FilterChips, type FilterChip } from "@/components/filter-chips"
import { Page, PageBody, PageCount, PageHeader } from "@/components/page"
import { SearchInput } from "@/components/search-input"
import { StateView } from "@/components/state-view"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { atUsername } from "@/features/accounts/username"
import { fmtInt } from "@/lib/format"
import { notify } from "@/lib/notify"

import { LEVEL_CHIPS, LOGS_CONFIRM, LOGS_LABEL, LOGS_TOAST } from "./labels"
import { useLogsView } from "./logs-view"
import { filterLogs, logKey, type LevelFilter } from "./log-filter"
import { LogRow } from "./log-row"

/* Журнал: записи в стор кладёт живой поток, экран только фильтрует и листает.
   Список идёт во всю ширину сразу под шапкой, без карточки. Страница не
   скроллится — прокрутка внутри списка; высота страницы ровно в окно минус
   нижняя навигация телефона. Нажатие по @юзернейму в строке оставляет журнал
   этого аккаунта — снимается крестиком на его плашке. */

export default function LogsPage() {
  useLanguage()
  const events = useLogs((s) => s.events)
  const debug = useLogs((s) => s.debug)
  const setDebug = useLogs((s) => s.setDebug)
  const markSeen = useLogs((s) => s.markSeen)
  const level = useLogsView((s) => s.level)
  const setLevel = useLogsView((s) => s.setLevel)
  const search = useLogsView((s) => s.search)
  const setSearch = useLogsView((s) => s.setSearch)
  const account = useLogsView((s) => s.account)
  const setAccount = useLogsView((s) => s.setAccount)

  // вошли на экран — ошибки считаются просмотренными, отметка в меню гаснет
  useEffect(() => {
    markSeen()
  }, [markSeen])

  const view = useMemo(
    () => filterLogs(events, { debug, level, search, account }),
    [events, debug, level, search, account]
  )
  const chips: FilterChip<LevelFilter>[] = LEVEL_CHIPS.map((chip) => ({
    ...chip,
    count: view.counts[chip.value],
  }))

  const scrollRef = useRef<HTMLDivElement>(null)
  // виртуализатор отдаёт изменяемые функции — правило предупреждает компилятор
  // React, которого в сборке нет; других способов пользоваться им нет
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: view.items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 36,
    overscan: 12,
  })

  const reset = () => {
    setSearch("")
    setLevel("all")
    setAccount(null)
  }

  const clear = async () => {
    const ok = await confirmDestructive({
      title: LOGS_CONFIRM.clear,
      description: LOGS_CONFIRM.clearDesc,
      confirmText: LOGS_CONFIRM.clearYes,
    })
    if (!ok) return
    try {
      await clearLogs()
      notify.ok(LOGS_TOAST.cleared)
    } catch (error) {
      notify.error(error, LOGS_TOAST.notCleared)
    }
  }

  /* Записи приходят сверху: без якоря список уезжает под курсором — читаешь
     одно, а на том же месте уже другое. Сдвигаем прокрутку на высоту
     вставленного, если список именно вырос и пользователь не в начале.
     Смена среза или поиска — это другой список, к его началу. */
  const anchor = useRef({ height: 0, view: "" })
  const viewKey = `${debug}|${level}|${search}|${account}`
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const prev = anchor.current
    if (prev.view !== viewKey) {
      el.scrollTop = 0
    } else if (el.scrollTop > 0 && el.scrollHeight > prev.height) {
      el.scrollTop += el.scrollHeight - prev.height
    }
    anchor.current = { height: el.scrollHeight, view: viewKey }
  }, [view.items, viewKey])

  return (
    <Page fill>
      <PageHeader
        title={sectionTitle("logs")}
        meta={<PageCount>{fmtInt(view.items.length)}</PageCount>}
        search={<SearchInput value={search} onValueChange={setSearch} placeholder={LOGS_LABEL.search} />}
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <FilterChips items={chips} value={level} onValueChange={setLevel} label={LOGS_LABEL.level} />
            {account ? (
              <span className="inline-flex h-7 items-center gap-1 rounded-full bg-secondary pr-1 pl-3 text-xs">
                {atUsername(account)}
                <button
                  type="button"
                  aria-label={LOGS_LABEL.resetAccount}
                  onClick={() => setAccount(null)}
                  className="flex size-5 items-center justify-center rounded-full text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <XIcon className="size-3.5" />
                </button>
              </span>
            ) : null}
          </div>
        }
        actions={
          <div className="flex items-center gap-2">
            <Switch id="logs-debug" checked={debug} onCheckedChange={(v) => setDebug(v)} />
            <Label htmlFor="logs-debug">{LOGS_LABEL.debug}</Label>
            <Button variant="outline" onClick={clear}>
              <Trash2Icon />
              {LOGS_LABEL.clear}
            </Button>
          </div>
        }
      />
      <PageBody bleed>
        {view.items.length ? (
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
            <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const item = view.items[virtualRow.index]
                return (
                  <div
                    key={logKey(item, virtualRow.index)}
                    data-index={virtualRow.index}
                    ref={virtualizer.measureElement}
                    className="absolute top-0 left-0 w-full"
                    style={{ transform: `translateY(${virtualRow.start}px)` }}
                  >
                    <LogRow item={item} onAccount={setAccount} />
                  </div>
                )
              })}
            </div>
          </div>
        ) : view.total ? (
          <StateView
            icon={SearchXIcon}
            title={LOGS_LABEL.notFound}
            action={
              <Button variant="outline" size="sm" onClick={reset}>
                {LOGS_LABEL.reset}
              </Button>
            }
          />
        ) : (
          <StateView icon={ScrollTextIcon} title={LOGS_LABEL.empty} />
        )}
      </PageBody>
    </Page>
  )
}
