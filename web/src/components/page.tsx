import { cn } from "@/lib/utils"

/* Каркас экрана: липкая шапка (название, счётчик, действия справа — главное
   последним) и тело. Левый край у всех экранов один и тот же: шапка всегда во
   всю ширину, тело прижато влево, и при смене раздела заголовок не прыгает.
   Ширина ограничивается только у тела, и задаётся один раз здесь: списки —
   во всю ширину, формы — до 1152 или 768 px. bleed — список во всю ширину
   без отступов и карточки: таблица начинается сразу под шапкой. */

const WIDTH = {
  full: "",
  wide: "max-w-6xl",
  narrow: "max-w-3xl",
} as const

export type PageWidth = keyof typeof WIDTH

/* fill — экран ровно в окно: страница не скроллится, прокрутка идёт внутри
   панелей (списки аккаунтов и журнала, обзор). Высота считается один раз
   здесь: на телефоне из окна вычитается нижняя навигация и safe-area. */
const FILL = "h-[calc(100svh_-_var(--mobile-nav-h)_-_env(safe-area-inset-bottom))] md:h-svh"

export function Page({
  fill,
  className,
  ...props
}: React.ComponentProps<"div"> & { fill?: boolean }) {
  return (
    <div
      data-slot="page"
      className={cn("flex flex-col", fill ? FILL : "min-h-full", className)}
      {...props}
    />
  )
}

interface PageHeaderProps {
  title: React.ReactNode
  /** счётчик или статус рядом с названием */
  meta?: React.ReactNode
  /** кнопки справа; главное действие — последним */
  actions?: React.ReactNode
  /** поиск: на широком окне — перед кнопками, на телефоне — своей строкой
      под заголовком, чтобы кнопки остались рядом с названием */
  search?: React.ReactNode
  /** вторая строка шапки: поиск, фильтры, сегменты */
  toolbar?: React.ReactNode
  className?: string
}

export function PageHeader({ title, meta, actions, search, toolbar, className }: PageHeaderProps) {
  return (
    <header
      data-slot="page-header"
      className={cn(
        "sticky top-0 z-30 border-b bg-background/85 backdrop-blur-md supports-backdrop-filter:bg-background/70",
        "pt-[env(safe-area-inset-top)]",
        className
      )}
    >
      <div className="flex w-full flex-col gap-3 px-4 py-3 md:px-6">
        <div
          className={cn(
            "grid min-h-8 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2",
            search
              ? "[grid-template-areas:'title_actions'_'search_search'] sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:[grid-template-areas:'title_search_actions']"
              : "[grid-template-areas:'title_actions']"
          )}
        >
          <div className="flex min-w-0 items-center gap-3 [grid-area:title]">
            <h1 className="truncate text-lg leading-7 font-semibold tracking-tight">{title}</h1>
            {meta}
          </div>
          {search ? <div className="min-w-0 [grid-area:search]">{search}</div> : null}
          {actions ? (
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 [grid-area:actions]">{actions}</div>
          ) : null}
        </div>
        {toolbar}
      </div>
    </header>
  )
}

export function PageBody({
  width = "full",
  bleed,
  className,
  ...props
}: React.ComponentProps<"div"> & { width?: PageWidth; bleed?: boolean }) {
  return (
    <div
      data-slot="page-body"
      className={cn(
        "flex w-full flex-1 flex-col",
        bleed ? "min-h-0" : "gap-4 px-4 py-4 md:px-6 md:py-6",
        WIDTH[width],
        className
      )}
      {...props}
    />
  )
}

/** Счётчик рядом с названием экрана. */
export function PageCount({ children }: { children: React.ReactNode }) {
  return <span className="tabular text-sm text-muted-foreground">{children}</span>
}
