import { localize } from "@/lib/i18n"
/* Тексты экрана «Профиль»: ключ к серверу, баланс и история списаний. */

export const PROFILE_LABEL = localize({
  profile: "Профиль",
  key: "Ключ",
  replaceKey: "Другой ключ",
  save: "Сохранить",
  remove: "Удалить",
  balance: "Баланс",
  until: "до",
  history: "История баланса",
  more: "Ещё",
  empty: "Движений пока нет",
  failed: "Не удалось",
  today: "Сегодня",
  yesterday: "Вчера",
  saved: "Ключ сохранён.",
  removed: "Ключ удалён.",
} as const)

export const PROFILE_STATUS: Record<
  string,
  { text: string; variant: "default" | "secondary" | "destructive" }
> = localize({
  active: { text: "Активен", variant: "default" },
  disabled: { text: "Отключён", variant: "destructive" },
  none: { text: "Нет ключа", variant: "secondary" },
  error: { text: "Нет связи", variant: "destructive" },
})
