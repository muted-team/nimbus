import type { LogItem } from "@/api/types"

/* Фильтрация журнала — чистая функция: экран логов и её тесты считают по
   одному правилу показанные записи и счётчики чипов.
   Пайплайн: подробности → уровень → поиск. */

export type LevelFilter = "all" | "err" | "warn"

export interface LogFilter {
  debug: boolean
  level: LevelFilter
  search: string
  /** только записи этого аккаунта (нажатие по юзернейму в строке) */
  account?: string | null
}

export interface LogView {
  /** показанные записи */
  items: LogItem[]
  /** счётчики чипов по набору после поиска, до среза уровнем */
  counts: Record<LevelFilter, number>
  /** записей в журнале после тумблера подробностей, до поиска и уровня */
  total: number
}

export function filterLogs(events: LogItem[], { debug, level, search, account }: LogFilter): LogView {
  const shown = debug ? events : events.filter((e) => !e.debug)
  const base = account ? shown.filter((e) => e.account === account) : shown
  // «@name» в поиске — тот же юзернейм: собака в журнале только для показа
  const q = search.trim().toLowerCase()
  const name = q.replace(/^@/, "")
  const searched = q
    ? base.filter((e) => e.text.toLowerCase().includes(q) || (!!name && (e.account ?? "").toLowerCase().includes(name)))
    : base
  const items = level === "all" ? searched : searched.filter((e) => e.level === level)
  return {
    items,
    total: base.length,
    counts: {
      all: searched.length,
      err: searched.filter((e) => e.level === "err").length,
      warn: searched.filter((e) => e.level === "warn").length,
    },
  }
}

/** Ключ строки: у записей сервера — номер, у своих записей интерфейса — индекс. */
export const logKey = (item: LogItem, index: number): string =>
  item.seq ? String(item.seq) : `local-${index}`
