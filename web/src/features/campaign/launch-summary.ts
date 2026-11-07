import { localize, t } from "@/lib/i18n"
import { atUsername } from "@/features/accounts/username"
import { count, fmtInt, plural } from "@/lib/format"

import { CLEANUP_ALL, CLEANUP_OFF, CLEANUP_SAME, shownCreatives, type FormValues, type ParsedForm } from "./form-model"
import { CONFIRM_LABEL, CREATIVES_LABEL, MEDIA_LABEL, REPEAT_UNIT_LABEL, SHORTAGE_LABEL } from "./labels"
import type { SlotShortage } from "./shortage"

/* Сводка перед запуском — одна на все виды запуска: вся публикация с экрана,
   выбранные аккаунты или повтор неудачных. */

export interface LaunchTarget {
  /** только эти аккаунты; без них — все */
  accounts?: string[]
  /** сколько всего аккаунтов, если запуск по всем (может быть ещё неизвестно) */
  total?: number
}

const PAST_POSTS: [string, string, string] = localize(["прошлый пост", "прошлых поста", "прошлых постов"])
const ACCOUNTS_GEN: [string, string, string] = localize(["аккаунта", "аккаунтов", "аккаунтов"])

export function launchTitle({ accounts }: LaunchTarget): string {
  if (!accounts) return CONFIRM_LABEL.all
  if (accounts.length === 1) return t("Опубликовать с {0}?", [atUsername(accounts[0])])
  return t("Опубликовать с {0}?", [count(accounts.length, ACCOUNTS_GEN)])
}

function cleanupText(code: number, posts: number): string {
  if (code === CLEANUP_ALL) return CONFIRM_LABEL.allPosts
  return count(code === CLEANUP_SAME ? posts : code, PAST_POSTS)
}

/** «каждые 2–4 ч», «каждые 30 мин», «каждый час». */
export function repeatText({ min, max, unit }: NonNullable<ParsedForm["repeat"]>): string {
  const short = REPEAT_UNIT_LABEL[unit].short
  if (min !== max) return t("каждые {0}–{1} {2}", [fmtInt(min), fmtInt(max), short])
  if (min === 1) return unit === "hour" ? t("каждый час") : t("каждую минуту")
  return t("{0} {1} {2}", [plural(min, [t("каждый"), t("каждые"), t("каждые")]), fmtInt(min), short])
}

/** short — папки, которых не хватит на проход (см. shortage.ts): о них
    говорим сразу после строки «Контент», это она и есть. */
export function launchSummary(
  v: FormValues,
  p: ParsedForm,
  target: LaunchTarget,
  short: SlotShortage[] = []
) {
  const accounts = target.accounts?.length ?? target.total
  const creatives = CREATIVES_LABEL[v.media][shownCreatives(v.media, v.creatives)]
  const details: [string, string][] = []
  if (accounts !== undefined) details.push([CONFIRM_LABEL.accounts, fmtInt(accounts)])
  details.push(
    [CONFIRM_LABEL.posts, fmtInt(p.posts)],
    [CONFIRM_LABEL.content, MEDIA_LABEL[v.media]]
  )
  // режим отдельной строкой: «Фото · Одно фото, одна копия» в узкой сводке
  // рвалось посреди слов
  if (creatives) details.push([CONFIRM_LABEL.mode, creatives])
  for (const slot of short) {
    details.push([SHORTAGE_LABEL.folder(v.media, slot.index), SHORTAGE_LABEL.need(v.media, slot.need, slot.have)])
  }
  details.push([CONFIRM_LABEL.after, v.keep ? CONFIRM_LABEL.kept : CONFIRM_LABEL.deleted])
  if (p.cleanup !== CLEANUP_OFF) details.push([CONFIRM_LABEL.cleanup, cleanupText(p.cleanup, p.posts)])
  if (p.repeat) details.push([CONFIRM_LABEL.repeat, repeatText(p.repeat)])
  return { title: launchTitle(target), details }
}
