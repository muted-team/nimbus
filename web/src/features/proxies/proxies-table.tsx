import { useLanguage } from "@/lib/i18n"
import { ArrowDownIcon, ArrowUpIcon } from "lucide-react"

import { Hint } from "@/components/hint"
import { SelectionBarSpacer, type BarAction } from "@/components/selection-bar"
import { Checkbox } from "@/components/ui/checkbox"
import { useNow } from "@/hooks/use-now"
import { fmtInt } from "@/lib/format"
import type { PickMode } from "@/lib/selection"
import { cn } from "@/lib/utils"

import { CELL, COUNTRY_COLUMN, NUM_COLUMNS } from "./columns"
import type { ProxyRow, SortDir, SortKey } from "./filter"
import { nowTickMs } from "./health"
import { COLUMN_LABEL, loginHint, PROXIES_LABEL, publishHint } from "./labels"
import { ProxyTableRow, type ProxyRowActions } from "./proxy-row"

/* Настоящая `<table>`, не сетка: ширину колонок считает браузер сам — по
   самому длинному значению, а короче заголовка — по заголовку (обычная
   авто-раскладка `<table>`). Строк десятки, не сотни (T-195) — виртуализация
   не нужна, и без неё нет причины держать каждую строку в своей отдельной
   сетке (там `max-content` между сетками не выровнять — этим и была прибита
   ширина в rem раньше). Липкая шапка — `position: sticky` на самих `<th>`.

   Выравнивание колонки — один класс (`CELL` из columns.ts) на `<th>` и на
   `<td>`: они не могут разойтись, потому что берут его из одного места. */

const TH = "sticky top-0 z-10 border-b bg-background px-3 py-2 text-xs font-normal text-muted-foreground"

export function ProxiesTable({
  rows,
  fetchedAt,
  sort,
  dir,
  onSort,
  rotateBusy,
  actions,
  marked,
  selected,
  onPick,
  onPickAll,
  bulk,
}: {
  rows: ProxyRow[]
  /** когда пришёл этот снимок, мс эпохи (dataUpdatedAt у запроса) */
  fetchedAt: number
  sort: SortKey
  dir: SortDir
  onSort: (key: SortKey) => void
  /** номер строки, у которой сейчас идёт смена IP */
  rotateBusy: number | null
  actions: ProxyRowActions
  /** сколько строк отмечено для входа и для публикации — числом в шапке колонки */
  marked: { login: number; publish: number }
  selected: Set<number>
  onPick: (index: number, mode: PickMode) => void
  /** флажок в шапке: true — выбрать все видимые, false — снять */
  onPickAll: (all: boolean) => void
  /** действия над всем выбором — меню по правому клику по выбранной строке */
  bulk: BarAction[]
}) {
  useLanguage()
  // «N мин назад» и отсчёт смены IP растут своим ходом
  const now = useNow(nowTickMs(rows))
  const elapsed = fetchedAt ? Math.max(0, Math.floor((now - fetchedAt) / 1000)) : 0
  const picked = rows.reduce((n, r) => n + (selected.has(r.index) ? 1 : 0), 0)
  const all = picked > 0 && picked === rows.length

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <table className="w-full border-collapse text-row">
        <thead>
          <tr>
            <th className={cn(TH, "w-8 pl-4 md:pl-6")}>
              <Checkbox
                checked={all}
                indeterminate={picked > 0 && !all}
                aria-label={all ? PROXIES_LABEL.pickNone : PROXIES_LABEL.pickAll}
                onCheckedChange={() => onPickAll(!all)}
              />
            </th>
            <SortTh
              label={COLUMN_LABEL.index}
              column="index"
              sort={sort}
              dir={dir}
              onSort={onSort}
              cell={cn(TH, CELL.index)}
            />
            <SortTh
              label={COLUMN_LABEL.proxy}
              column="proxy"
              sort={sort}
              dir={dir}
              onSort={onSort}
              cell={cn(TH, CELL.proxy)}
            />
            <SortTh
              label={COUNTRY_COLUMN.label}
              column="country"
              sort={sort}
              dir={dir}
              onSort={onSort}
              cell={cn(TH, COUNTRY_COLUMN.cell)}
            />
            <th className={cn(TH, CELL.scheme)}>{COLUMN_LABEL.scheme}</th>
            <th className={cn(TH, CELL.state)}>{COLUMN_LABEL.state}</th>
            {NUM_COLUMNS.map((c) => (
              <SortTh
                key={c.key}
                label={c.label}
                column={c.key}
                sort={sort}
                dir={dir}
                onSort={onSort}
                cell={cn(TH, c.cell)}
              />
            ))}
            <MarkedTh label={COLUMN_LABEL.login} n={marked.login} hint={loginHint(marked.login)} cell={cn(TH, CELL.login)} />
            <MarkedTh
              label={COLUMN_LABEL.publish}
              n={marked.publish}
              hint={publishHint(marked.publish)}
              cell={cn(TH, CELL.publish)}
            />
            <th className={cn(TH, "z-20 pr-4 md:pr-6", CELL.actions)} />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <ProxyTableRow
              key={row.index}
              row={row}
              elapsed={elapsed}
              rotateBusy={rotateBusy === row.index}
              actions={actions}
              selected={selected.has(row.index)}
              onPick={onPick}
              selectionCount={selected.size}
              bulk={bulk}
            />
          ))}
        </tbody>
      </table>
      {/* распорка под панель выделения: без неё она накрывает последние строки */}
      {selected.size ? <SelectionBarSpacer /> : null}
    </div>
  )
}

/* Шапка колонки отметок: число отмеченных рядом с подписью. Ноль — жёлтым:
   без отмеченных вход (публикация) остановится; подсказка говорит об этом
   словами. Раньше то же самое стояло двумя строками над таблицей. */
function MarkedTh({ label, n, hint, cell }: { label: string; n: number; hint: string; cell: string }) {
  useLanguage()
  return (
    <th className={cell}>
      <Hint label={hint}>
        <span className="inline-flex cursor-default items-center gap-1 whitespace-nowrap">
          {label}
          <span className={cn("tabular", n ? "text-foreground" : "text-warning")}>{fmtInt(n)}</span>
        </span>
      </Hint>
    </th>
  )
}

/* Заголовок колонки: нажатие ставит сортировку по ней, повторное —
   разворачивает порядок. Выравнивание кнопки внутри — из `cell` (тот же
   класс, что у ячеек строк): подпись со стрелкой стоит ровно там же, где
   стоят значения, а не отдельно настроенным `justify-*`. */
function SortTh({
  label,
  column,
  sort,
  dir,
  onSort,
  cell,
}: {
  label: string
  column: SortKey
  sort: SortKey
  dir: SortDir
  onSort: (key: SortKey) => void
  cell: string
}) {
  useLanguage()
  const on = sort === column
  const Arrow = dir === "asc" ? ArrowUpIcon : ArrowDownIcon
  return (
    <th className={cell}>
      <button
        type="button"
        onClick={() => onSort(column)}
        className={cn(
          "inline-flex items-center gap-1 rounded-sm py-1 outline-none transition-colors",
          "hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
          on && "text-foreground"
        )}
      >
        <span className="whitespace-nowrap">{label}</span>
        {on ? <Arrow className="size-3.5 shrink-0" /> : null}
      </button>
    </th>
  )
}
