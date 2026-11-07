import { fetchSlotInfo, useSlotInfo } from "@/api/misc"
import type { SlotInfo } from "@/api/types"
import { useDebounced } from "@/hooks/use-debounced"

import { activeSlots, type FormValues } from "./form-model"
import { useFormStore } from "./form-store"

/* Числа по папкам формы: сколько фото (видео) лежит в каждой. Запрос один на
   всех, кому он нужен, — и строки папок, и подтверждение запуска берут числа
   отсюда. Путь набирают руками, поэтому запрос уходит с задержкой. */

const TYPING_PAUSE_MS = 400

export function useSlotFiles(): Map<string, SlotInfo> | undefined {
  const values = useFormStore((s) => s.values)
  const key = useDebounced(values ? activeSlots(values).join("\n") : "", TYPING_PAUSE_MS)
  const { data } = useSlotInfo(key ? key.split("\n") : [])
  return data
}

/**
 * Числа по папкам без ожидания рендера — для запуска с экранов, где форма
 * подгружается тем же кликом (`ensureFormValues` в launcher.ts): к этому
 * моменту у `useSlotFiles` ещё нет свежих папок, оно узнает о них только на
 * следующем рендере. Кэш общий с `useSlotInfo`, так что при недавнем визите на
 * экран публикации второй сетевой запрос не уходит.
 *
 * Сбой запроса — `undefined`, а не исключение: без чисел запуск всё равно
 * возможен, просто подтверждение не скажет о нехватке файлов.
 */
export async function fetchSlotFiles(values: FormValues): Promise<Map<string, SlotInfo> | undefined> {
  const folders = activeSlots(values)
  if (!folders.length) return undefined
  try {
    return await fetchSlotInfo(folders)
  } catch {
    return undefined
  }
}
