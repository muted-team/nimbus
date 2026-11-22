import { useMediaQuery } from "@/hooks/use-media-query"

import type { SortKey } from "./filter"
import { COLUMN_LABEL } from "./labels"

/* Прежние числовые колонки сохраняют ярусы ширины. Новые поля включаются
   отдельно; если человек выбрал больше места, прокручивается сама таблица.
   Шапка и строки строят сетку из одного списка. */

export type Tier = 0 | 1 | 2 | 3

export type ColumnKey = SortKey | "avatar"

export interface Column {
  key: ColumnKey
  label: string
  width: string
  /** с какого яруса колонка помещается */
  tier: Tier
  align: "start" | "center" | "end"
  /** Новые необязательные поля не меняют привычный набор колонок. */
  defaultHidden?: boolean
}

export const COLUMNS: Column[] = [
  { key: "avatar", label: COLUMN_LABEL.avatar, width: "2rem", tier: 0, align: "center" },
  { key: "name", label: COLUMN_LABEL.name, width: "8rem", tier: 0, align: "start" },
  { key: "nickname", label: COLUMN_LABEL.nickname, width: "12rem", tier: 1, align: "start", defaultHidden: true },
  { key: "login", label: COLUMN_LABEL.login, width: "14rem", tier: 1, align: "start", defaultHidden: true },
  { key: "user_id", label: COLUMN_LABEL.user_id, width: "12rem", tier: 1, align: "start", defaultHidden: true },
  { key: "region", label: COLUMN_LABEL.region, width: "5.5rem", tier: 1, align: "center" },
  { key: "followers", label: COLUMN_LABEL.followers, width: "6rem", tier: 1, align: "end" },
  { key: "following", label: COLUMN_LABEL.following, width: "6rem", tier: 1, align: "end", defaultHidden: true },
  { key: "likes", label: COLUMN_LABEL.likes, width: "5rem", tier: 3, align: "end" },
  { key: "views", label: COLUMN_LABEL.views, width: "6rem", tier: 3, align: "end" },
  { key: "posts", label: COLUMN_LABEL.posts, width: "4.5rem", tier: 1, align: "end" },
  { key: "shadow", label: COLUMN_LABEL.shadow, width: "5rem", tier: 2, align: "end" },
  { key: "verified", label: COLUMN_LABEL.verified, width: "6rem", tier: 1, align: "center", defaultHidden: true },
  { key: "private", label: COLUMN_LABEL.private, width: "6rem", tier: 1, align: "center", defaultHidden: true },
  { key: "fetched", label: COLUMN_LABEL.fetched, width: "6.5rem", tier: 2, align: "end" },
]

/** Ярус по ширине окна. */
export function useTier(): Tier {
  const md = useMediaQuery("(min-width: 768px)")
  const xl = useMediaQuery("(min-width: 1280px)")
  const xxl = useMediaQuery("(min-width: 1536px)")
  return xxl ? 3 : xl ? 2 : md ? 1 : 0
}

/** Колонки, которые стоят в строке на этой ширине с этим выбором. */
export const visibleColumns = (tier: Tier, hidden: ReadonlySet<ColumnKey>) =>
  COLUMNS.filter((c) => (c.tier <= tier || c.defaultHidden) && !hidden.has(c.key))

/* Колонка действий широкая, только когда в списке есть кому входить: у
   «Войти» есть слово, и на тач-экране кнопка ещё шире. В срезе «Готовы»
   входить некому — там остаётся место под одно троеточие, без пустой полосы. */
export function gridTemplate(columns: Column[], tier: Tier, loginButton: boolean): string {
  const actions = loginButton ? (tier ? "8.5rem" : "5rem") : "2.5rem"
  const primary = columns.find((c) => c.key === "name" || c.key === "login" || c.key === "nickname")?.key
  return ["2rem", ...columns.map((c) => c.key === primary ? `minmax(${c.width},1fr)` : c.width), actions].join(" ")
}
