import { t, useLanguage } from "@/lib/i18n"
import type { UseQueryResult } from "@tanstack/react-query"
import { CircleAlertIcon, RotateCcwIcon, type LucideIcon } from "lucide-react"

import { errorText } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

/* Пустое, ошибочное и загрузочное состояния — одним видом на все экраны:
   иконка, короткая строка, при необходимости пояснение и одно действие. */

interface StateViewProps {
  icon: LucideIcon
  title: React.ReactNode
  /** пояснение под заголовком */
  text?: React.ReactNode
  action?: React.ReactNode
  tone?: "default" | "error"
  className?: string
}

export function StateView({
  icon: Icon,
  title,
  text,
  action,
  tone = "default",
  className,
}: StateViewProps) {
  return (
    <Empty className={cn("py-10", className)}>
      <EmptyHeader>
        <EmptyMedia
          variant="icon"
          className={cn("size-10 rounded-full", tone === "error" && "bg-destructive/15 text-destructive")}
        >
          <Icon className="size-5" />
        </EmptyMedia>
        <EmptyTitle className="text-sm font-medium">{title}</EmptyTitle>
        {text ? <EmptyDescription className="text-xs">{text}</EmptyDescription> : null}
      </EmptyHeader>
      {action ? <EmptyContent>{action}</EmptyContent> : null}
    </Empty>
  )
}

export function ErrorView({
  error,
  onRetry,
  className,
}: {
  error: unknown
  onRetry?: () => void
  className?: string
}) {
  useLanguage()
  return (
    <StateView
      icon={CircleAlertIcon}
      tone="error"
      title={errorText(error)}
      className={className}
      action={
        onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RotateCcwIcon />{t("Повторить")}</Button>
        ) : null
      }
    />
  )
}

/** Заглушка строк списка на время первой загрузки. */
export function LoadingRows({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2 p-4", className)} aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" style={{ opacity: 1 - i * (0.8 / rows) }} />
      ))}
    </div>
  )
}

/**
 * Состояния запроса одним компонентом: первая загрузка — заглушка, ошибка без
 * данных — ошибка с «Повторить», данные — children(data).
 */
export function QueryView<T>({
  query,
  loading,
  children,
}: {
  query: UseQueryResult<T>
  loading?: React.ReactNode
  children: (data: T) => React.ReactNode
}) {
  if (query.data !== undefined) return <>{children(query.data)}</>
  if (query.isError) return <ErrorView error={query.error} onRetry={() => void query.refetch()} />
  return <>{loading ?? <LoadingRows />}</>
}
