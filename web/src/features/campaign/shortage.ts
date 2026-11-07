import type { Creatives, MediaKind, SlotInfo } from "@/api/types"

import { parseInteger, type FormValues } from "./form-model"

/* Хватит ли файлов в папках на проход кампании. Считаем по расходу, а не на
   глаз: за него отвечает modules/batch_publish.py — разные креативы берут
   свой файл на каждый пост, одинаковые держат один комплект на весь прогон
   аккаунта. Файлы, которые велено оставлять, идут по кругу и не кончаются. */

export interface SlotShortage {
  /** номер папки на экране, с нуля */
  index: number
  /** сколько файлов нужно в этой папке */
  need: number
  /** сколько в ней есть */
  have: number
}

/** Сколько файлов в папке для текущего вида контента. */
export const slotFileCount = (info: SlotInfo, media: MediaKind) =>
  media === "video" ? info.videos : info.photos

/**
 * Сколько файлов нужно в одной папке-слоте. Оставленные файлы идут по кругу,
 * но круг из пустой папки не начать — хотя бы один файл нужен. null — считать
 * нечего: неизвестно, сколько будет аккаунтов.
 */
export function filesPerFolder(
  creatives: Creatives,
  posts: number,
  accounts: number | undefined,
  keep: boolean
): number | null {
  if (keep) return 1
  if (!accounts) return null
  // «разные фото»/«разные видео» — свой файл на пост, прочие режимы — по файлу
  // на аккаунт: комплект держится весь его прогон
  return creatives === "unique" ? accounts * posts : accounts
}

/**
 * Папки, которых не хватит на проход, — с числом нужных и наличных файлов.
 * Пустой список: файлов хватает, их велено оставлять или папка ещё не выбрана
 * (об этом строка папки говорит сама). Индекс — сырой, по позиции в форме
 * (`photoSlots`/`videoSlots`), а не по списку без пустых строк: строка формы
 * рисуется по тому же сырому списку, и номер должен совпадать с тем, что
 * показывает пометка нехватки под нужной папкой, а не под соседней пустой.
 */
export function findShortage(
  values: FormValues,
  info: Map<string, SlotInfo> | undefined,
  accounts: number | undefined
): SlotShortage[] {
  // «Постов на аккаунт» не набрано — форма ещё не готова, и считать не по
  // чему: запуск удержит своя проверка поля
  const posts = parseInteger(values.posts, 1)
  const need = posts === null ? null : filesPerFolder(values.creatives, posts, accounts, values.keep)
  if (need === null || !info) return []
  const rawSlots = values.media === "video" ? values.videoSlots : values.photoSlots
  const short: SlotShortage[] = []
  rawSlots.forEach((raw, index) => {
    const path = raw.trim()
    if (!path) return
    const slot = info.get(path)
    if (!slot?.exists) return
    const have = slotFileCount(slot, values.media)
    if (have < need) short.push({ index, need, have })
  })
  return short
}
