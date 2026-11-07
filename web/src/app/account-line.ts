import { t } from "@/lib/i18n"
import { useLicense } from "@/api/license"
import { fmtDec } from "@/lib/format"

/* Кто вошёл и сколько на балансе — строка меню профиля на компьютере и в
   «Ещё» на телефоне. */

export const CONTACT = {
  text: "@emptyenemy",
  href: "https://t.me/emptyenemy",
} as const

/** Строка под именем: баланс, а без ключа — его состояние. */
export function useAccountLine(): {
  name: string
  line: string
  avatar?: string | null
} {
  const { data } = useLicense()
  const name = data?.name || t(t("Профиль"))
  if (!data) return { name, line: "" }
  if (data.status === "none") return { name, line: t(t("Нет ключа")) }
  if (data.status === "error") return { name, line: t(t("Нет связи")) }
  const balance = data.balance == null ? "—" : fmtDec(data.balance)
  return {
    name,
    line: `${balance} ${data.currency || "₽"}`,
    avatar: data.avatar_url,
  }
}
