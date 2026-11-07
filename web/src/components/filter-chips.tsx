import { ToggleGroup as ToggleGroupPrimitive } from "@base-ui/react/toggle-group"
import { Toggle as TogglePrimitive } from "@base-ui/react/toggle"

import { cn } from "@/lib/utils"

import { toneText, type Tone } from "./status"

/* Срезы списка чипами со счётчиками: «Все 50 · Без входа 7 · С ошибкой 3».
   Выбран всегда ровно один; стрелки ходят по чипам. Один вид для аккаунтов,
   логов и результатов публикации. */

export interface FilterChip<V extends string> {
  value: V
  label: string
  count?: number
  /** цвет счётчика, когда в срезе что-то есть */
  tone?: Tone
  /** не показывать чип с нулём */
  hideEmpty?: boolean
}

export function FilterChips<V extends string>({
  items,
  value,
  onValueChange,
  label,
  className,
}: {
  items: FilterChip<V>[]
  value: V
  onValueChange: (value: V) => void
  /** доступное имя группы */
  label: string
  className?: string
}) {
  const visible = items.filter((it) => !it.hideEmpty || it.count || it.value === value)
  return (
    <ToggleGroupPrimitive
      aria-label={label}
      value={[value]}
      onValueChange={(next) => {
        if (next.length) onValueChange(next[0] as V)
      }}
      className={cn("flex min-w-0 flex-wrap items-center gap-2", className)}
    >
      {visible.map((it) => (
        <TogglePrimitive
          key={it.value}
          value={it.value}
          className={cn(
            "inline-flex h-7 items-center gap-2 rounded-full border px-3 text-xs whitespace-nowrap text-muted-foreground transition-colors outline-none select-none",
            "hover:bg-accent/50 hover:text-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            "data-pressed:border-transparent data-pressed:bg-secondary data-pressed:text-foreground",
            "pointer-coarse:h-9 pointer-coarse:px-4 pointer-coarse:text-sm"
          )}
        >
          {it.label}
          {it.count !== undefined ? (
            <span className={cn("tabular", it.count && it.tone ? toneText[it.tone] : "opacity-70")}>
              {it.count}
            </span>
          ) : null}
        </TogglePrimitive>
      ))}
    </ToggleGroupPrimitive>
  )
}
