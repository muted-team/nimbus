import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/* Карточка раздела экрана: заголовок слева, действия справа, тело. Один вид
   на всё приложение — шапка одной высоты, одинаковые отступы. flush — тело
   без внутренних отступов (таблица или список во всю ширину карточки). */

interface PanelProps extends Omit<React.ComponentProps<"section">, "title"> {
  title?: React.ReactNode
  icon?: LucideIcon
  /** счётчик или статус рядом с заголовком */
  meta?: React.ReactNode
  actions?: React.ReactNode
  flush?: boolean
  bodyClassName?: string
}

export function Panel({
  title,
  icon: Icon,
  meta,
  actions,
  flush,
  className,
  bodyClassName,
  children,
  ...props
}: PanelProps) {
  const hasHeader = title || actions
  return (
    <section
      data-slot="panel"
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card text-card-foreground",
        className
      )}
      {...props}
    >
      {hasHeader ? (
        <div className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
          {title ? (
            <h2 className="flex min-w-0 flex-1 items-center gap-2 text-sm font-semibold">
              {Icon ? <Icon className="size-4 shrink-0 text-muted-foreground" /> : null}
              <span className="truncate">{title}</span>
              {meta}
            </h2>
          ) : (
            <div className="flex-1" />
          )}
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col",
          !flush && "gap-4 px-4 pb-4",
          !flush && !hasHeader && "pt-4",
          flush && hasHeader && "border-t",
          bodyClassName
        )}
      >
        {children}
      </div>
    </section>
  )
}
