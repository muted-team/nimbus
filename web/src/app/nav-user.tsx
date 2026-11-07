import { useLanguage } from "@/lib/i18n"
import { useState } from "react"
import {
  ChevronsUpDownIcon,
  HistoryIcon,
  MessageCircleIcon,
} from "lucide-react"
import { useLocation } from "wouter"

import { useChangelog } from "@/api/misc"
import { UserAvatar } from "@/components/user-avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { ChangesDialog } from "@/features/changes/changes-dialog"
import { CHANGES_LABEL } from "@/features/changes/labels"
import { openExternal } from "@/lib/native"

import { CONTACT, useAccountLine } from "./account-line"
import { SECTIONS } from "./sections"

/* Меню профиля внизу бокового меню: кто вошёл и баланс, профиль, настройки,
   «Что нового», версия. Служебное собрано здесь, чтобы список разделов
   оставался рабочим. */

export function NavUser() {
  useLanguage()
  const [, navigate] = useLocation()
  const { isMobile } = useSidebar()
  const { data: changelog } = useChangelog()
  const { name, line, avatar } = useAccountLine()
  const [changes, setChanges] = useState(false)
  const service = SECTIONS.filter((s) => s.secondary)

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton
                size="lg"
                className="data-popup-open:bg-sidebar-accent"
                tooltip={name}
              />
            }
          >
            <UserAvatar url={avatar} name={name} />
            <span className="grid min-w-0 flex-1 text-left leading-tight">
              <span className="truncate text-sm">{name}</span>
              <span className="truncate text-xs text-muted-foreground tabular">
                {line}
              </span>
            </span>
            <ChevronsUpDownIcon className="ml-auto text-muted-foreground" />
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side={isMobile ? "bottom" : "right"}
            align="end"
            sideOffset={8}
            className="min-w-56"
          >
            <DropdownMenuGroup>
              {service.map((s) => (
                <DropdownMenuItem key={s.id} onClick={() => navigate(s.path)}>
                  <s.icon />
                  {s.title}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem onClick={() => setChanges(true)}>
                <HistoryIcon />
                {CHANGES_LABEL.title}
              </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => void openExternal(CONTACT.href)}>
              <MessageCircleIcon />
              {CONTACT.text}
            </DropdownMenuItem>
            {/* подпись меню живёт только внутри группы — без неё Base UI падает */}
            {changelog?.version ? (
              <DropdownMenuGroup>
                <DropdownMenuLabel className="tabular">
                  v{changelog.version}
                </DropdownMenuLabel>
              </DropdownMenuGroup>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
      <ChangesDialog open={changes} onOpenChange={setChanges} />
    </SidebarMenu>
  )
}
