import { localize, t, useLanguage } from "@/lib/i18n"
import { Fragment, useLayoutEffect, useRef, useState } from "react"
import { ChevronDownIcon, XIcon, type LucideIcon } from "lucide-react"

import { IconButton } from "@/components/hint"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle } from "@/components/ui/drawer"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useMediaQuery } from "@/hooks/use-media-query"

/* Панель над выделением в таблице — одна для аккаунтов и прокси. На
   компьютере первые действия кнопками одной полосой, остальное — в «Ещё»:
   девять кнопок подряд на 1280 переносились в два ряда. На телефоне — одна
   строка «Выбрано 3 · Действия», список выезжает снизу.

   Панель висит поверх списка и меряет себя сама: высоту кладёт в
   --selection-bar, а список ставит внизу распорку этой высоты
   (SelectionBarSpacer) — иначе последние строки остались бы под панелью. */

export interface BarAction {
  key: string
  label: string
  icon: LucideIcon
  onClick: () => void
  disabled?: boolean
  destructive?: boolean
  /** черта перед пунктом в меню */
  separatorBefore?: boolean
}

const TEXT = localize({
  count: (n: number) => t("Выбрано: {0}", [n]),
  more: "Ещё",
  actions: "Действия",
  clear: "Снять выделение",
} as const)

export function SelectionBar({
  count,
  actions,
  main = 3,
  onClear,
  children,
}: {
  count: number
  actions: BarAction[]
  /** сколько первых действий — кнопками, остальное в «Ещё» */
  main?: number
  onClear: () => void
  /** строка над действиями: ход идущей работы */
  children?: React.ReactNode
}) {
  useLanguage()
  const phone = useMediaQuery("(max-width: 767px)")
  const [drawer, setDrawer] = useState(false)
  if (!count && !children) return null

  const buttons = actions.slice(0, main)
  const rest = actions.slice(main)
  const run = (a: BarAction) => {
    setDrawer(false)
    a.onClick()
  }

  return (
    <Floating>
      {children}
      {count ? (
        <div className="flex items-center justify-center gap-2">
          <span className="px-1 text-sm text-muted-foreground tabular">{TEXT.count(count)}</span>
          {phone ? (
            <Button variant="outline" size="sm" onClick={() => setDrawer(true)}>
              {TEXT.actions}
            </Button>
          ) : (
            <ButtonGroup>
              {buttons.map((a) => (
                <Button
                  key={a.key}
                  variant={a.destructive ? "destructive" : "outline"}
                  size="sm"
                  disabled={a.disabled}
                  onClick={a.onClick}
                >
                  <a.icon />
                  {a.label}
                </Button>
              ))}
              {rest.length ? (
                <DropdownMenu>
                  <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    {TEXT.more}
                    <ChevronDownIcon data-icon="inline-end" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" side="top" className="min-w-48">
                    {rest.map((a) => (
                      <Fragment key={a.key}>
                        {a.separatorBefore ? <DropdownMenuSeparator /> : null}
                        <DropdownMenuItem
                          disabled={a.disabled}
                          variant={a.destructive ? "destructive" : "default"}
                          onClick={() => run(a)}
                        >
                          <a.icon />
                          {a.label}
                        </DropdownMenuItem>
                      </Fragment>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : null}
            </ButtonGroup>
          )}
          <IconButton label={TEXT.clear} icon={XIcon} size="icon-sm" hotkey="Escape" onClick={onClear} />
        </div>
      ) : null}
      <Drawer open={drawer && phone} onOpenChange={setDrawer}>
        <DrawerContent className="pb-[env(safe-area-inset-bottom)]">
          <DrawerHeader className="text-left">
            <DrawerTitle className="tabular">{TEXT.count(count)}</DrawerTitle>
          </DrawerHeader>
          <div className="flex flex-col p-2">
            {actions.map((a) => (
              <Fragment key={a.key}>
                {a.separatorBefore ? <div className="my-1 h-px bg-border" /> : null}
                <button
                  type="button"
                  disabled={a.disabled}
                  onClick={() => run(a)}
                  data-variant={a.destructive ? "destructive" : undefined}
                  className="flex h-12 items-center gap-3 rounded-lg px-3 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent disabled:opacity-50 data-[variant=destructive]:text-destructive [&_svg]:size-5 [&_svg]:text-muted-foreground data-[variant=destructive]:[&_svg]:text-destructive"
                >
                  <a.icon />
                  {a.label}
                </button>
              </Fragment>
            ))}
          </div>
        </DrawerContent>
      </Drawer>
    </Floating>
  )
}

/** Распорка в конце списка под висящую панель. */
export function SelectionBarSpacer() {
  return <div style={{ height: "var(--selection-bar, 4rem)" }} />
}

function Floating({ children }: { children: React.ReactNode }) {
  useLanguage()
  const ref = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    const root = document.documentElement
    if (!el) return
    const publish = () => {
      // +8 — зазор между панелью и низом списка, чтобы не упирались вплотную
      root.style.setProperty("--selection-bar", `${el.offsetHeight + 8}px`)
    }
    publish()
    const observer = new ResizeObserver(publish)
    observer.observe(el)
    return () => {
      observer.disconnect()
      root.style.removeProperty("--selection-bar")
    }
  }, [])

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-4 z-20 flex justify-center px-4">
      <div
        ref={ref}
        className="animate-in fade-in slide-in-from-bottom-2 zoom-in-95 pointer-events-auto flex max-w-full flex-col items-center gap-2 rounded-xl border bg-card/95 p-2 shadow-lg backdrop-blur duration-150"
      >
        {children}
      </div>
    </div>
  )
}
