import { useLanguage } from "@/lib/i18n"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { ArrowDownIcon, ArrowUpIcon } from "lucide-react"

import type { Account, StudioCountersMap } from "@/api/types"
import { SelectionBarSpacer } from "@/components/selection-bar"
import { Checkbox } from "@/components/ui/checkbox"
import { cn } from "@/lib/utils"

import { AccountRow, type RowHandlers } from "./account-row"
import type { SelectionTarget } from "./actions"
import type { Column } from "./columns"
import type { SortDir, SortKey } from "./filter"
import { COLUMN_LABEL, SELECT_LABEL } from "./labels"

/* Таблица аккаунтов: липкая шапка с флажком «выбрать все» и сортировкой,
   виртуализованный список. Шапка живёт внутри области прокрутки — так её
   колонки всегда совпадают со строками, даже когда справа появляется полоса
   прокрутки. Разметка — роли таблицы: строки, ячейки, aria-sort у колонки,
   по которой отсортировано. */

export function AccountsTable({
  accounts,
  avatars,
  counters,
  busyNames,
  locked,
  selected,
  sort,
  dir,
  onSort,
  columns,
  template,
  handlers,
  selection,
  onPickAll,
  padBottom,
}: {
  accounts: Account[]
  avatars?: Record<string, string>
  /** числа студии по аккаунтам: стоят выше чисел профиля */
  counters?: StudioCountersMap
  /** аккаунты, которыми сейчас занимаются: спиннер у логина */
  busyNames: Set<string>
  locked: boolean
  selected: Set<string>
  sort: SortKey
  dir: SortDir
  onSort: (key: SortKey) => void
  columns: Column[]
  template: string
  handlers: RowHandlers
  selection: SelectionTarget
  /** флажок в шапке: true — выбрать все видимые, false — снять */
  onPickAll: (all: boolean) => void
  /** внизу висит панель выделения — освобождаем место, чтобы она не накрыла строки */
  padBottom?: boolean
}) {
  useLanguage()
  const scrollRef = useRef<HTMLDivElement>(null)
  const headRef = useRef<HTMLDivElement>(null)
  /* Шапка стоит перед списком в той же прокрутке, поэтому строки начинаются не
     с нуля: её высоту виртуализатор должен знать, иначе к концу списка он
     ошибается на эту высоту и последняя строка не доезжает. */
  const [headH, setHeadH] = useState(0)
  useLayoutEffect(() => {
    setHeadH(headRef.current?.offsetHeight ?? 0)
  }, [])

  // виртуализатор отдаёт изменяемые функции — правило предупреждает компилятор
  // React, которого в сборке нет; других способов пользоваться им нет
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: accounts.length,
    getScrollElement: () => scrollRef.current,
    // на телефоне строка выше: под логином там строка с числами
    estimateSize: () => (columns.length ? 40 : 49),
    overscan: 12,
    scrollMargin: headH,
  })

  // сменили порядок — смотреть продолжаем с начала списка
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [sort, dir])

  const picked = accounts.reduce((n, a) => n + (selected.has(a.username) ? 1 : 0), 0)
  const all = picked > 0 && picked === accounts.length

  return (
    <div ref={scrollRef} role="table" aria-rowcount={accounts.length} className="min-h-0 flex-1 overflow-y-auto">
      <div
        ref={headRef}
        role="row"
        style={{ gridTemplateColumns: template }}
        className="sticky top-0 z-10 grid w-full items-center gap-x-3 border-b bg-background px-4 py-1 md:px-6 text-xs text-muted-foreground"
      >
        <div className="flex items-center" role="columnheader">
          <Checkbox
            checked={all}
            indeterminate={picked > 0 && !all}
            aria-label={all ? SELECT_LABEL.none : SELECT_LABEL.all}
            onCheckedChange={() => onPickAll(!all)}
          />
        </div>
        <SortButton label={COLUMN_LABEL.name} column="name" sort={sort} dir={dir} onSort={onSort} />
        {columns.map((c) => (
          <SortButton
            key={c.key}
            label={c.label}
            column={c.key}
            sort={sort}
            dir={dir}
            onSort={onSort}
            align={c.align}
          />
        ))}
        <div role="columnheader" />
      </div>

      <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const account = accounts[virtualRow.index]
          return (
            <div
              key={account.username}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              className="absolute top-0 left-0 w-full"
              style={{ transform: `translateY(${virtualRow.start - headH}px)` }}
            >
              <AccountRow
                account={account}
                avatar={avatars?.[account.username]}
                counters={counters}
                busy={busyNames.has(account.username)}
                locked={locked}
                selected={selected.has(account.username)}
                columns={columns}
                template={template}
                handlers={handlers}
                selection={selection}
              />
            </div>
          )
        })}
      </div>
      {/* панель выделения висит поверх списка — без распорки она накрывает
          последние строки, и до них не добраться прокруткой; высоту панель
          кладёт сама в переменную (см. accounts-bar.tsx) */}
      {padBottom ? <SelectionBarSpacer /> : null}
    </div>
  )
}

/* Заголовок колонки: нажатие ставит сортировку по ней, повторное —
   разворачивает порядок. Стрелка стоит только у колонки, по которой
   отсортировано, — иначе шапка рябит. */
function SortButton({
  label,
  column,
  sort,
  dir,
  onSort,
  align = "start",
}: {
  label: string
  column: SortKey
  sort: SortKey
  dir: SortDir
  onSort: (key: SortKey) => void
  align?: "start" | "end" | "center"
}) {
  useLanguage()
  const on = sort === column
  const Arrow = dir === "asc" ? ArrowUpIcon : ArrowDownIcon
  return (
    <div
      className="min-w-0"
      role="columnheader"
      aria-sort={on ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        className={cn(
          "flex h-8 w-full min-w-0 items-center gap-1 rounded-sm outline-none transition-colors",
          "hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
          align === "end" ? "justify-end" : align === "center" ? "justify-center" : "justify-start",
          on && "text-foreground"
        )}
      >
        <span className="truncate">{label}</span>
        {on ? <Arrow className="size-3.5 shrink-0" /> : null}
      </button>
    </div>
  )
}
