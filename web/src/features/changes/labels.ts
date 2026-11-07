import { localize } from "@/lib/i18n"
/* Подписи «Что нового»: окно и пункт меню профиля называют его одинаково. */

export const CHANGES_LABEL = localize({
  title: "Что нового",
  current: "сейчас",
  empty: "Информация отсутствует",
  emptyRelease: "Информация отсутствует.",
} as const)
