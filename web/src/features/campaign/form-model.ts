import type { CampaignForm, CampaignStartBody, Creatives, MediaKind, RepeatUnit } from "@/api/types"
import { parseNumber } from "@/components/number-input"
import { fmtDec } from "@/lib/format"

import { ERROR_TEXT, FIELD_ORDER, fieldLabel, type CleanupMode, type FieldKey } from "./labels"

/* Форма публикации: значения полей как набраны (строки), разбор в числа,
   проверка и тела запросов. Чистая логика без React — её же берут экран
   публикации и запуск с других экранов. */

export interface FormValues {
  media: MediaKind
  title: string
  caption: string
  /** фото-папки и папка с видео хранятся раздельно: смена режима их не сбивает */
  photoSlots: string[]
  videoSlots: string[]
  posts: string
  /** пауза перед постом, секунды с дробью */
  delayMin: string
  delayMax: string
  creatives: Creatives
  keep: boolean
  cleanup: boolean
  cleanupMode: CleanupMode
  cleanupCount: string
  repeat: boolean
  repeatMin: string
  repeatMax: string
  repeatUnit: RepeatUnit
}

export const DEFAULT_POSTS = 6

/** Коды очистки на сервере: 0 — выкл, -1 — все посты, -2 — сколько зальём, N — ровно N. */
export const CLEANUP_OFF = 0
export const CLEANUP_ALL = -1
export const CLEANUP_SAME = -2

export type FormErrors = Partial<Record<FieldKey, string>>

/** Разобранная проверенная форма — только из неё строится запуск. */
export interface ParsedForm {
  slots: string[]
  posts: number
  delayMinMs: number
  delayMaxMs: number
  cleanup: number
  repeat: { min: number; max: number; unit: RepeatUnit } | null
}

/* ── числа ──────────────────────────────────────────────────────────── */

/** Целое не меньше min или null. */
export function parseInteger(raw: string, min: number): number | null {
  const n = parseNumber(raw)
  return n !== null && Number.isInteger(n) && n >= min ? n : null
}

/** Секунды поля -> мс для сервера; пусто — 0, мусор и минус — null. */
export function secondsToMs(raw: string): number | null {
  const n = parseNumber(raw, 0)
  return n === null || n < 0 ? null : Math.round(n * 1000)
}

/** мс сервера -> секунды для поля: «1,50», «4» — без разрядов. */
export function msToSeconds(ms: number): string {
  return fmtDec(ms / 1000).replace(/\s/g, "")
}

export const trimSlots = (slots: string[]) => slots.map((s) => s.trim()).filter(Boolean)

/** Папки текущего режима, без пустых строк. */
export const activeSlots = (v: FormValues) => trimSlots(v.media === "video" ? v.videoSlots : v.photoSlots)

/** Креативы, как их показывать: у видео «копии разные» — это «одно видео». */
export const shownCreatives = (media: MediaKind, creatives: Creatives): Creatives =>
  media === "video" && creatives === "copies" ? "single" : creatives

/** Код очистки для сервера; null — число очистки набрано с ошибкой. */
export function cleanupCode(v: Pick<FormValues, "cleanup" | "cleanupMode" | "cleanupCount">): number | null {
  if (!v.cleanup) return CLEANUP_OFF
  if (v.cleanupMode === "all") return CLEANUP_ALL
  if (v.cleanupMode === "same") return CLEANUP_SAME
  return parseInteger(v.cleanupCount, 1)
}

/* ── сервер -> форма ────────────────────────────────────────────────── */

const countText = (n: number | undefined) => (n && n > 0 ? String(n) : "")

export function fromServer(form: CampaignForm): FormValues {
  const del = form.delete_before ?? CLEANUP_OFF
  const ppa = form.posts_per_account
  return {
    media: form.media === "video" ? "video" : "photo",
    title: form.title ?? "",
    caption: form.caption ?? "",
    photoSlots: form.slots ?? [],
    videoSlots: (form.video_slots ?? []).slice(0, 1),
    posts: String(ppa && ppa >= 1 ? ppa : DEFAULT_POSTS),
    delayMin: form.min_delay_ms != null ? msToSeconds(form.min_delay_ms) : "",
    delayMax: form.max_delay_ms != null ? msToSeconds(form.max_delay_ms) : "",
    creatives: form.creatives ?? "copies",
    keep: !!form.keep_photos,
    cleanup: del !== CLEANUP_OFF,
    cleanupMode: del === CLEANUP_ALL ? "all" : del > 0 ? "count" : "same",
    cleanupCount: countText(del),
    repeat: !!form.repeat,
    repeatMin: countText(form.repeat_min),
    repeatMax: countText(form.repeat_max),
    repeatUnit: form.repeat_unit === "min" ? "min" : "hour",
  }
}

/* ── форма -> сервер ────────────────────────────────────────────────── */

/**
 * Форма для автосохранения. Недонабранное (пустое «Постов», мусор в паузе)
 * не отправляется — на сервере остаётся прежнее значение.
 */
export function toServerForm(v: FormValues): CampaignForm {
  const body: CampaignForm = {
    media: v.media,
    slots: trimSlots(v.photoSlots),
    video_slots: trimSlots(v.videoSlots),
    creatives: v.creatives,
    keep_photos: v.keep,
    caption: v.caption,
    title: v.title,
    repeat: v.repeat,
    repeat_unit: v.repeatUnit,
  }
  const posts = parseInteger(v.posts, 1)
  if (posts !== null) body.posts_per_account = posts
  const dMin = secondsToMs(v.delayMin)
  const dMax = secondsToMs(v.delayMax)
  if (dMin !== null) body.min_delay_ms = dMin
  if (dMax !== null) body.max_delay_ms = dMax
  const del = cleanupCode(v)
  if (del !== null) body.delete_before = del
  const rMin = parseInteger(v.repeatMin, 0)
  const rMax = parseInteger(v.repeatMax, 0)
  if (rMin !== null) body.repeat_min = rMin
  if (rMax !== null) body.repeat_max = rMax
  return body
}

/** Проверка перед запуском: ошибки по полям и, если их нет, разобранная форма. */
export function checkForm(v: FormValues): { errors: FormErrors; parsed: ParsedForm | null } {
  const errors: FormErrors = {}

  const slots = activeSlots(v)
  if (!slots.length) errors.folders = ERROR_TEXT.folder

  const posts = parseInteger(v.posts, 1)
  if (posts === null) errors.posts = ERROR_TEXT.int1

  const delayMinMs = secondsToMs(v.delayMin)
  const delayMaxMs = secondsToMs(v.delayMax)
  if (delayMinMs === null || delayMaxMs === null) errors.delay = ERROR_TEXT.num0
  else if (delayMinMs > delayMaxMs) errors.delay = ERROR_TEXT.order

  const cleanup = cleanupCode(v)
  if (cleanup === null) errors.cleanupCount = ERROR_TEXT.int1

  let repeat: ParsedForm["repeat"] = null
  if (v.repeat) {
    const min = parseInteger(v.repeatMin, 1)
    const max = parseInteger(v.repeatMax, 1)
    if (min === null || max === null) errors.repeat = ERROR_TEXT.int1
    else if (min > max) errors.repeat = ERROR_TEXT.order
    else repeat = { min, max, unit: v.repeatUnit }
  }

  const ok =
    !Object.keys(errors).length && posts !== null && delayMinMs !== null && delayMaxMs !== null && cleanup !== null
  return {
    errors,
    parsed: ok ? { slots, posts, delayMinMs, delayMaxMs, cleanup, repeat } : null,
  }
}

/** Первая по порядку на экране ошибка — строкой для тоста: «Постов: целое число от 1.» */
export function firstErrorText(errors: FormErrors, media: MediaKind): string | null {
  const field = FIELD_ORDER.find((f) => errors[f])
  if (!field) return null
  const msg = errors[field]!
  return `${fieldLabel(field, media)}: ${msg.charAt(0).toLowerCase()}${msg.slice(1)}.`
}

/** Тело запуска из проверенной формы; accounts — только эти аккаунты. */
export function toStartBody(v: FormValues, p: ParsedForm, accounts?: string[]): CampaignStartBody {
  const body: CampaignStartBody = {
    media: v.media,
    slots: p.slots,
    caption: v.caption,
    title: v.media === "video" ? "" : v.title,
    min_delay_ms: p.delayMinMs,
    max_delay_ms: p.delayMaxMs,
    posts_per_account: p.posts,
    delete_before: p.cleanup,
    creatives: v.creatives,
    keep_photos: v.keep,
    repeat: !!p.repeat,
  }
  if (p.repeat) {
    body.repeat_unit = p.repeat.unit
    body.repeat_min = p.repeat.min
    body.repeat_max = p.repeat.max
  }
  if (accounts) body.accounts = accounts
  return body
}
