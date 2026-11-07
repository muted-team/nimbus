import { localize } from "@/lib/i18n"
import {
  CircleUserRoundIcon,
  GlobeIcon,
  ImagesIcon,
  ScrollTextIcon,
  SendIcon,
  Settings2Icon,
  UsersRoundIcon,
  type LucideIcon,
} from "lucide-react"

/* Разделы приложения — единственный список: из него строятся боковое меню,
   нижняя навигация на телефоне, горячие клавиши Alt+1…9 и маршруты.

   Рабочих разделов пять, по одному на тип объекта: публикация (стартовый —
   одна главная работа на одном экране), аккаунты, прокси, креативы и журнал.
   Профиль и настройки — не рабочие разделы: они в меню профиля внизу
   бокового меню, как nav-user в блоках shadcn. «Что нового» открывается
   окном оттуда же, своего маршрута у него нет. */

export type SectionId =
  "camp" | "accounts" | "proxies" | "media" | "logs" | "settings" | "profile"

export interface Section {
  id: SectionId
  path: string
  title: string
  icon: LucideIcon
  /** в нижней навигации телефона; остальное — в меню профиля */
  mobile?: boolean
  /** служебные разделы — в меню профиля, а не в списке разделов */
  secondary?: boolean
}

export const SECTIONS: Section[] = localize([
  { id: "camp", path: "/", title: "Публикация", icon: SendIcon, mobile: true },
  {
    id: "accounts",
    path: "/accounts",
    title: "Аккаунты",
    icon: UsersRoundIcon,
    mobile: true,
  },
  {
    id: "proxies",
    path: "/proxies",
    title: "Прокси",
    icon: GlobeIcon,
    mobile: true,
  },
  {
    id: "media",
    path: "/media",
    title: "Креативы",
    icon: ImagesIcon,
    mobile: true,
  },
  { id: "logs", path: "/logs", title: "Логи", icon: ScrollTextIcon },
  {
    id: "profile",
    path: "/profile",
    title: "Профиль",
    icon: CircleUserRoundIcon,
    secondary: true,
  },
  {
    id: "settings",
    path: "/settings",
    title: "Настройки",
    icon: Settings2Icon,
    secondary: true,
  },
])

/* Адреса прежних разделов: сохранённый «последний раздел» и закладки ведут
   туда, где та же работа живёт теперь. */
export const MOVED: Record<string, string> = {
  "/publish": "/",
  "/uniq": "/media/uniq",
  "/changes": "/",
}

const sectionOf = (id: SectionId) => SECTIONS.find((s) => s.id === id)!

export const sectionPath = (id: SectionId) => sectionOf(id).path

/** Название раздела: его же показывают меню, нижняя навигация и шапка экрана. */
export const sectionTitle = (id: SectionId) => sectionOf(id).title

/** Раздел, к которому относится адрес: у креативов есть вложенные (/media/…). */
export function sectionAt(location: string): Section | undefined {
  return SECTIONS.find((s) =>
    s.path === "/"
      ? location === "/"
      : location === s.path || location.startsWith(`${s.path}/`)
  )
}
