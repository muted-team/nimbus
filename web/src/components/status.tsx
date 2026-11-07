import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/* Смысловые цвета одним словарём: зелёный — хорошо, жёлтый — внимание,
   красный — плохо, акцентный индиго — идёт работа, серый — нейтрально. Цветом
   помечается маленький элемент (точка, иконка, число), а не весь текст. */

export type Tone = "neutral" | "ok" | "warn" | "bad" | "live"

export const toneText: Record<Tone, string> = {
  neutral: "text-muted-foreground",
  ok: "text-success",
  warn: "text-warning",
  bad: "text-destructive",
  live: "text-primary",
}

export const toneBg: Record<Tone, string> = {
  neutral: "bg-muted-foreground/50",
  ok: "bg-success",
  warn: "bg-warning",
  bad: "bg-destructive",
  live: "bg-primary",
}

export const toneSoft: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  ok: "bg-success/15 text-success",
  warn: "bg-warning/15 text-warning",
  bad: "bg-destructive/15 text-destructive",
  live: "bg-primary/15 text-primary",
}

export function StatusDot({ tone, pulse, className }: { tone: Tone; pulse?: boolean; className?: string }) {
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)} aria-hidden>
      {pulse ? (
        <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", toneBg[tone])} />
      ) : null}
      <span className={cn("relative inline-flex size-2 rounded-full", toneBg[tone])} />
    </span>
  )
}

/** Мягкая плашка статуса: иконка + короткое слово. */
export function StatusBadge({
  tone,
  icon: Icon,
  spin,
  children,
  className,
}: {
  tone: Tone
  icon?: LucideIcon
  spin?: boolean
  children: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-2 rounded-full px-3 text-xs font-medium whitespace-nowrap",
        toneSoft[tone],
        className
      )}
    >
      {Icon ? <Icon className={cn("size-3.5", spin && "animate-spin")} /> : null}
      {children}
    </span>
  )
}

/** Плитка-счётчик: подпись, крупное число, строка под ним. Кликабельная — если есть onClick. */
export function Stat({
  label,
  value,
  sub,
  icon: Icon,
  tone = "neutral",
  onClick,
  className,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  icon?: LucideIcon
  tone?: Tone
  onClick?: () => void
  className?: string
}) {
  const Tag = onClick ? "button" : "div"
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className={cn(
        "group/stat flex min-w-0 flex-col gap-1 rounded-xl border bg-card p-4 text-left outline-none",
        onClick &&
          "transition-colors hover:bg-accent/40 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
        className
      )}
    >
      <span className="flex items-center gap-2 text-xs text-muted-foreground">
        {Icon ? <Icon className={cn("size-3.5", toneText[tone])} /> : null}
        <span className="truncate">{label}</span>
      </span>
      <span className="tabular truncate text-2xl leading-8 font-semibold tracking-tight">{value}</span>
      {sub ? <span className="truncate text-xs text-muted-foreground">{sub}</span> : null}
    </Tag>
  )
}
