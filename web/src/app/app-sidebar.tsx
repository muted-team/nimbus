import { t, useLanguage } from "@/lib/i18n"
import { Link, useLocation } from "wouter"

import { Hint } from "@/components/hint"
import { toneBg, toneSoft } from "@/components/status"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { Spinner } from "@/components/ui/spinner"
import { cn } from "@/lib/utils"

import { BrandMark, PRODUCT } from "./brand"
import { useNavBadges, type NavBadge } from "./nav-status"
import { NavUser } from "./nav-user"
import { SECTIONS, sectionAt } from "./sections"

/* Боковое меню: знак и имя продукта, пять рабочих разделов, меню профиля
   внизу. Навигация отступает назад: неактивные пункты приглушены, активный —
   цветом текста; работа на экране, а не в меню. */

function Badge({ badge }: { badge: NavBadge }) {
  return (
    <SidebarMenuBadge
      className={cn(
        "gap-1 rounded-full px-2",
        toneSoft[badge.tone]
      )}
    >
      {badge.spin ? <Spinner className="size-3" /> : null}
      {badge.text}
    </SidebarMenuBadge>
  )
}

function NavItems() {
  useLanguage()
  const [location] = useLocation()
  const badges = useNavBadges()
  const current = sectionAt(location)
  return (
    <SidebarMenu className="gap-1">
      {SECTIONS.filter((s) => !s.secondary).map((s) => {
        const badge = badges[s.id]
        const active = current?.id === s.id
        return (
          <SidebarMenuItem key={s.id}>
            <SidebarMenuButton
              isActive={active}
              tooltip={s.title}
              aria-current={active ? "page" : undefined}
              className="text-muted-foreground hover:text-foreground data-active:font-medium data-active:text-sidebar-accent-foreground data-active:shadow-[inset_2px_0_0_var(--primary)]"
              render={<Link href={s.path} />}
            >
              <s.icon />
              <span>{s.title}</span>
            </SidebarMenuButton>
            {badge ? <Badge badge={badge} /> : null}
            {/* в свёрнутом меню отметка — точкой на иконке */}
            {badge ? (
              <span
                className={cn(
                  "pointer-events-none absolute top-1 right-1 hidden size-2 rounded-full group-data-[collapsible=icon]:block",
                  toneBg[badge.tone]
                )}
              />
            ) : null}
          </SidebarMenuItem>
        )
      })}
    </SidebarMenu>
  )
}

export function AppSidebar() {
  useLanguage()
  return (
    <Sidebar collapsible="icon" className="select-none">
      <SidebarHeader className="h-14 flex-row items-center gap-2 px-3 group-data-[collapsible=icon]:px-2">
        <BrandMark className="size-7 group-data-[collapsible=icon]:hidden" />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold group-data-[collapsible=icon]:hidden">
          {PRODUCT}
        </span>
        <Hint label={t("Меню")} hotkey="Mod+B" side="right">
          <SidebarTrigger className="text-muted-foreground" />
        </Hint>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <NavItems />
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
    </Sidebar>
  )
}
