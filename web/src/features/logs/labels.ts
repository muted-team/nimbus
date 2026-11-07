import { localize, t } from "@/lib/i18n"
import type { LogItem, LogLevel } from "@/api/types"
import type { FilterChip } from "@/components/filter-chips"
import type { Tone } from "@/components/status"

import type { LevelFilter } from "./log-filter"

/* Словари журнала: тон точки по уровню записи, чипы фильтра уровня и пометка
   записи прошлого запуска.
   Счётчики чипам добавляет экран по текущему набору записей. */

export const LEVEL_TONE: Record<LogLevel, Tone> = {
  "": "neutral",
  ok: "ok",
  warn: "warn",
  err: "bad",
}

export const LEVEL_CHIPS: Omit<FilterChip<LevelFilter>, "count">[] = localize([
  { value: "all", label: "все" },
  { value: "err", label: "ошибки", tone: "bad", hideEmpty: true },
  { value: "warn", label: "внимание", tone: "warn", hideEmpty: true },
])

export const LOGS_LABEL = localize({
  clear: "Очистить",
  copy: "Скопировать",
  search: "Поиск по логам",
  level: "Уровень",
  debug: "Подробно",
  account: "Аккаунт",
  resetAccount: "Все логи",
  notFound: "Ничего не найдено",
  reset: "Сбросить",
  empty: "Логов пока нет",
} as const)

export const LOGS_CONFIRM = localize({
  clear: "Очистить логи?",
  clearDesc: "Записи не восстановить.",
  clearYes: "Очистить",
} as const)

export const LOGS_TOAST = localize({
  cleared: "Логи очищены.",
  notCleared: "Не удалось очистить логи",
  copied: "Строка скопирована.",
} as const)

export type RowMarkKind = "source" | "past"

/** Запись поднята из файла событий прошлого запуска (см. modules/eventlog.py):
    показываем её, но за свежую принимать нельзя. */
export const PAST_LABEL = "прошлый запуск"

/** Что стоит перед текстом строки: у подробности — источник, у записи прошлого
    запуска — пометка; у свежего события ничего. */
export function rowMark(item: LogItem): { kind: RowMarkKind; text: string } | null {
  if (item.debug && item.source) return { kind: "source", text: item.source }
  if (item.past) return { kind: "past", text: t(PAST_LABEL) }
  return null
}

/** Вид пометки: источник — мелкая надпись, прошлый запуск — плашка. */
export const ROW_MARK_CLASS: Record<RowMarkKind, string> = {
  source: "shrink-0 text-xs text-muted-foreground",
  past: "shrink-0 rounded-full bg-muted px-2 text-xs whitespace-nowrap text-muted-foreground",
}
