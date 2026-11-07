import { t, useLanguage } from "@/lib/i18n"
import { HistoryIcon, MessageCircleIcon } from "lucide-react"
import { useState } from "react"
import { Link, useLocation } from "wouter"

import { useChangelog } from "@/api/misc"
import { UserAvatar } from "@/components/user-avatar"
import { toneBg } from "@/components/status"
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer"
import { ChangesDialog } from "@/features/changes/changes-dialog"
import { CHANGES_LABEL } from "@/features/changes/labels"
import { openExternal } from "@/lib/native"
import { cn } from "@/lib/utils"

import { CONTACT, useAccountLine } from "./account-line"
import { useNavBadges } from "./nav-status"
import { SECTIONS, sectionAt } from "./sections"

/* Телефон: четыре главных раздела в порядке бокового меню и профиль с остальным:
   логи, баланс, настройки, «Что нового». Высота панели —
   --mobile-nav-h: на неё отступает содержимое, а нижние панели экранов
   (действия над выделением) встают поверх неё. */

const itemClass =
  "relative flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-lg text-xs text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring active:bg-accent/50 aria-[current=page]:text-foreground"

const rowClass =
  "flex h-12 w-full items-center gap-3 rounded-lg px-3 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent aria-[current=page]:bg-accent"

export function MobileNav() {
  useLanguage()
  const [location] = useLocation()
  const [more, setMore] = useState(false)
  const [changes, setChanges] = useState(false)
  const badges = useNavBadges()
  const { data: changelog } = useChangelog()
  const { name, line, avatar } = useAccountLine()
  const current = sectionAt(location)
  const main = SECTIONS.filter((s) => s.mobile)
  const rest = SECTIONS.filter((s) => !s.mobile)
  const inRest = !!current && !current.mobile

  return (
    <>
      <nav
        aria-label={t("Разделы")}
        className="fixed inset-x-0 bottom-0 z-40 border-t bg-sidebar/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md select-none md:hidden"
      >
        <div className="flex h-(--mobile-nav-h) items-stretch px-1 py-1">
          {main.map((s) => {
            const badge = badges[s.id]
            const active = current?.id === s.id
            return (
              <Link
                key={s.id}
                href={s.path}
                aria-current={active ? "page" : undefined}
                className={itemClass}
              >
                <span
                  className={cn(
                    "flex h-7 w-12 items-center justify-center rounded-full transition-colors",
                    active && "bg-secondary text-foreground"
                  )}
                >
                  <s.icon className="size-5" />
                </span>
                <span className="max-w-full truncate">{s.title}</span>
                {badge ? (
                  <span
                    className={cn(
                      "absolute top-1 left-1/2 ml-3 size-2 rounded-full ring-2 ring-sidebar",
                      toneBg[badge.tone]
                    )}
                  />
                ) : null}
              </Link>
            )
          })}
          <button
            type="button"
            className={itemClass}
            aria-label={name}
            aria-current={inRest ? "page" : undefined}
            onClick={() => setMore(true)}
          >
            <span
              className={cn(
                "flex h-7 w-12 items-center justify-center rounded-full",
                inRest && "bg-secondary text-foreground"
              )}
            >
              <UserAvatar url={avatar} name={name} />
            </span>
            <span className="max-w-full truncate">{t("Профиль")}</span>
          </button>
        </div>
      </nav>

      <Drawer open={more} onOpenChange={setMore}>
        <DrawerContent className="pb-[env(safe-area-inset-bottom)]">
          <DrawerHeader className="text-left">
            <DrawerTitle className="flex items-center gap-3">
              <UserAvatar url={avatar} name={name} size="lg" />
              {name}
            </DrawerTitle>
            {line ? (
              <span className="text-sm text-muted-foreground tabular">
                {line}
              </span>
            ) : null}
          </DrawerHeader>
          <div className="flex flex-col p-2">
            {rest.map((s) => (
              <Link
                key={s.id}
                href={s.path}
                onClick={() => setMore(false)}
                aria-current={current?.id === s.id ? "page" : undefined}
                className={rowClass}
              >
                <s.icon className="size-5 text-muted-foreground" />
                {s.title}
              </Link>
            ))}
            <button
              type="button"
              className={rowClass}
              onClick={() => {
                setMore(false)
                setChanges(true)
              }}
            >
              <HistoryIcon className="size-5 text-muted-foreground" />
              {CHANGES_LABEL.title}
            </button>
          </div>
          <div className="flex items-center justify-between px-5 pt-1 pb-4 text-xs text-muted-foreground">
            {changelog?.version ? (
              <span className="tabular">v{changelog.version}</span>
            ) : (
              <span />
            )}
            <button
              type="button"
              onClick={() => void openExternal(CONTACT.href)}
              className="inline-flex items-center gap-1 text-foreground"
            >
              <MessageCircleIcon className="size-3.5" />
              {CONTACT.text}
            </button>
          </div>
        </DrawerContent>
      </Drawer>
      <ChangesDialog open={changes} onOpenChange={setChanges} />
    </>
  )
}
