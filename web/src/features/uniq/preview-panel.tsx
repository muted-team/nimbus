import { t, useLanguage } from "@/lib/i18n"
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { ChevronLeftIcon, ChevronRightIcon, RefreshCwIcon, TriangleAlertIcon } from "lucide-react"

import { errorText, userMessage } from "@/api/client"
import { previewUniq } from "@/api/misc"
import { UNIQ_KEYS, type MediaKind, type UniqPreviewItem, type UniqSettings } from "@/api/types"
import { Panel } from "@/components/panel"
import { StatusDot } from "@/components/status"
import { StateView } from "@/components/state-view"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { useHotkey } from "@/hooks/use-hotkey"
import { fmtSize, sentence } from "@/lib/format"
import { cn } from "@/lib/utils"

import { APPLIED_FORMAT, UNIQ_LABELS } from "./labels"
import { previewSignature } from "./param-model"
import { PREVIEW_EMPTY, previewEmpty } from "./preview-model"

/* Превью: обработанное фото из папок публикации. Запрос тяжёлый — уходит
   вручную и один раз при открытии; после правки настроек кнопка «Обновить»
   помечается точкой. В режиме видео превью нет: уникализатор к роликам не
   применяется, и фото-папки к текущему проходу отношения не имеют. */

interface PreviewPanelProps {
  settings: UniqSettings
  /** режим публикации: в видео превью по фото-папкам не собирается */
  media: MediaKind
  /** фото-папки публикации */
  folders: string[]
  /** форма публикации ещё не ответила — папки неизвестны */
  foldersReady: boolean
}

export function PreviewPanel({ settings, media, folders, foldersReady }: PreviewPanelProps) {
  useLanguage()
  const empty = previewEmpty(media, folders, foldersReady, settings.enabled)
  const canPreview = empty === null
  const sig = useMemo(() => previewSignature(folders, settings), [folders, settings])

  const [preview, setPreview] = useState<{ items: UniqPreviewItem[]; sig: string } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [slide, setSlide] = useState(0)

  const refresh = useCallback(async () => {
    if (busyRef.current || !canPreview) return
    busyRef.current = true
    setBusy(true)
    try {
      const res = await previewUniq(folders, settings)
      setPreview({ items: res.items, sig })
      setError(null)
    } catch (e) {
      setPreview(null)
      setError(e)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }, [canPreview, folders, settings, sig])

  useHotkey("Mod+Enter", () => void refresh())

  // один раз при открытии экрана, как только превью стало возможным
  const opened = useRef(false)
  useEffect(() => {
    if (opened.current || !canPreview) return
    opened.current = true
    void refresh()
  }, [canPreview, refresh])

  const stale = canPreview && preview !== null && preview.sig !== sig

  let body: ReactNode
  if (empty === "loading") {
    body = <Skeleton className="aspect-[3/4] w-full rounded-lg" />
  } else if (empty !== null) {
    body = <StateView {...PREVIEW_EMPTY[empty]} />
  } else if (preview === null) {
    body = error !== null ? <PreviewError text={errorText(error)} /> : <Skeleton className="aspect-[3/4] w-full rounded-lg" />
  } else if (preview.items.length === 0) {
    body = <PreviewError />
  } else {
    body = <Carousel items={preview.items} slide={slide} onSlide={setSlide} />
  }

  return (
    <Panel
      title={t("Превью")}
      actions={
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={busy || !canPreview}>
          {stale ? <StatusDot tone="warn" /> : null}
          {busy ? <Spinner className="size-3.5" /> : <RefreshCwIcon />}{t("Обновить")}</Button>
      }
    >
      {body}
    </Panel>
  )
}

function PreviewError({ text, className }: { text?: string; className?: string }) {
  useLanguage()
  return (
    <StateView
      icon={TriangleAlertIcon}
      tone="error"
      title={t("Не удалось")}
      text={text}
      className={className}
    />
  )
}

function Carousel({ items, slide, onSlide }: { items: UniqPreviewItem[]; slide: number; onSlide: (n: number) => void }) {
  useLanguage()
  const n = items.length
  // номер фото переживает «Обновить»: список мог стать короче
  const cur = Math.min(slide, n - 1)
  const item = items[cur]
  const step = (d: number) => onSlide((cur + d + n) % n)
  const applied = UNIQ_KEYS.flatMap((k) => {
    const v = item.applied?.[k]
    return v == null ? [] : [[k, v] as const]
  })
  const meta = Object.entries(item.meta ?? {})

  return (
    <div
      role="group"
      aria-label={t("Фото")}
      tabIndex={0}
      className="flex flex-col gap-3 rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      onKeyDown={(e) => {
        if (n < 2) return
        if (e.key === "ArrowLeft") {
          e.preventDefault()
          step(-1)
        } else if (e.key === "ArrowRight") {
          e.preventDefault()
          step(1)
        }
      }}
    >
      <div className="group/car relative">
        {item.error || !item.image ? (
          <div className="aspect-[3/4] w-full rounded-lg bg-muted">
            <PreviewError text={item.error ? sentence(userMessage(item.error)) : undefined} className="h-full" />
          </div>
        ) : (
          <img src={item.image} alt={item.name ?? ""} className="aspect-[3/4] w-full rounded-lg bg-muted object-cover" />
        )}
        {n > 1 ? (
          <>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("Предыдущее фото")}
              onClick={() => step(-1)}
              data-no-press-shift
              className="absolute top-1/2 left-1 z-10 -translate-y-1/2 bg-background/70 text-foreground opacity-100 backdrop-blur-sm transition-opacity hover:bg-background/90 hover:text-foreground md:opacity-0 md:group-hover/car:opacity-100 md:focus-visible:opacity-100"
            >
              <ChevronLeftIcon />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("Следующее фото")}
              onClick={() => step(1)}
              data-no-press-shift
              className="absolute top-1/2 right-1 z-10 -translate-y-1/2 bg-background/70 text-foreground opacity-100 backdrop-blur-sm transition-opacity hover:bg-background/90 hover:text-foreground md:opacity-0 md:group-hover/car:opacity-100 md:focus-visible:opacity-100"
            >
              <ChevronRightIcon />
            </Button>
          </>
        ) : null}
      </div>
      {n > 1 ? (
        <div className="flex items-center justify-center gap-2">
          {items.map((_, i) => (
            <button
              key={i}
              type="button"
              aria-label={t("Фото {0}", [i + 1])}
              onClick={() => onSlide(i)}
              className={cn(
                "relative size-1.5 rounded-full after:absolute after:-inset-2 after:content-['']",
                i === cur ? "bg-foreground" : "bg-muted-foreground/40 hover:bg-muted-foreground/70",
              )}
            />
          ))}
        </div>
      ) : null}
      {item.name || item.bytes != null ? (
        <div className="flex items-baseline justify-between gap-3">
          <span className="truncate text-xs">{item.name}</span>
          {item.bytes != null ? (
            <span className="shrink-0 text-xs text-muted-foreground tabular">{fmtSize(item.bytes)}</span>
          ) : null}
        </div>
      ) : null}
      {applied.length ? (
        <dl className="flex flex-col gap-1">
          {applied.map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-3 text-xs">
              <dt className="text-muted-foreground">{UNIQ_LABELS[k].label}</dt>
              <dd className="tabular">{APPLIED_FORMAT[k](v)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {meta.length ? (
        <div className="border-t pt-3">
          <dl className="flex flex-col gap-1">
            {meta.map(([k, v]) => (
              <div key={k} className="flex items-baseline justify-between gap-3 text-xs">
                <dt className="text-muted-foreground">{t(k)}</dt>
                <dd className="tabular">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </div>
  )
}
