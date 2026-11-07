import { useMediaQuery } from "@/hooks/use-media-query"

import type { SortKey } from "./filter"
import { COLUMN_LABEL } from "./labels"

/* Колонки таблицы аккаунтов. Две причины, по которым колонки нет в строке:
   ширина окна (ярус) и выбор человека (меню «Колонки»). Обе решаются здесь
   одним списком, а шаблон сетки строится из видимых — шапка и строки берут
   один и тот же, и разъехаться им негде.

   Ярусы выбраны по месту, которое остаётся логину:
     меньше 768 — логин и действия, числа под логином строкой;
     768 — страна, подписчики, посты;
     1280 — тень и время обновления;
     1536 — лайки и просмотры.
   Лайки с просмотрами последние нарочно: самые необязательные, а место под
   них нужно сразу у двух колонок. Яруса на 1024 нет: там боковое меню
   раскрывается с 48 до 256 пикселей, и колонки на этой же ширине отняли бы у
   логина всё.

   Страна стоит сразу за логином, а не среди чисел: это признак самого
   аккаунта. Ширину колонки задаёт подпись («Страна» со стрелкой), а не
   значение — иначе заголовок обрезался бы. */

export type Tier = 0 | 1 | 2 | 3

export type ColumnKey = Exclude<SortKey, "name">

export interface Column {
  key: ColumnKey
  label: string
  width: string
  /** с какого яруса колонка помещается */
  tier: Exclude<Tier, 0>
  align: "center" | "end"
}

export const COLUMNS: Column[] = [
  { key: "region", label: COLUMN_LABEL.region, width: "5.5rem", tier: 1, align: "center" },
  { key: "followers", label: COLUMN_LABEL.followers, width: "6rem", tier: 1, align: "end" },
  { key: "likes", label: COLUMN_LABEL.likes, width: "5rem", tier: 3, align: "end" },
  { key: "views", label: COLUMN_LABEL.views, width: "6rem", tier: 3, align: "end" },
  { key: "posts", label: COLUMN_LABEL.posts, width: "4.5rem", tier: 1, align: "end" },
  { key: "shadow", label: COLUMN_LABEL.shadow, width: "5rem", tier: 2, align: "end" },
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
  COLUMNS.filter((c) => c.tier <= tier && !hidden.has(c.key))

/* Колонка действий широкая, только когда в списке есть кому входить: у
   «Войти» есть слово, и на тач-экране кнопка ещё шире. В срезе «Готовы»
   входить некому — там остаётся место под одно троеточие, без пустой полосы. */
export function gridTemplate(columns: Column[], tier: Tier, loginButton: boolean): string {
  const actions = loginButton ? (tier ? "8.5rem" : "5rem") : "2.5rem"
  return ["2rem", "minmax(0,1fr)", ...columns.map((c) => c.width), actions].join(" ")
}
