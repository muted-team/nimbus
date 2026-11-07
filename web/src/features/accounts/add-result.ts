import type { BulkAddResponse } from "@/api/types"

import { ACC_TOAST, replacedWords } from "./labels"

/* Итог вставки списка аккаунтов — тостом. Сервер отвечает тремя наборами
   (T-122, modules/accounts.py): `added` — новые логины, `updated` — уже бывшие,
   у каждого названы заменённые поля, `errors` — неразобранные строки. Ключа
   `updated` в ответе нет, когда перезаписей не было. */

/** Тост про вставку: сколько прибавилось и сколько заменилось. Строк с ошибками
    здесь нет — они остаются в поле под панелью, с причиной у каждой. */
export function addedToast(res: BulkAddResponse): { text: string; lines?: string[] } | null {
  const updated = res.updated ?? []
  if (!res.added.length && !updated.length) return null

  /* Имена аккаунтов в тост не идут: при пачке строк их не прочесть, а кому
     именно заменили поля — видно в списке. Называем только поля. */
  const words = replacedWords(updated.flatMap((u) => u.replaced ?? []))
  const parts: string[] = []
  if (res.added.length) parts.push(ACC_TOAST.added(res.added.length))
  if (updated.length) parts.push(ACC_TOAST.updated(updated.length))
  return {
    text: parts.join(" "),
    lines: words.length ? [ACC_TOAST.replaced(words)] : undefined,
  }
}
