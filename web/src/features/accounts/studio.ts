import type { Account, StudioCountersMap } from "@/api/types"

/* Числа в строке аккаунта: свежие из студии, а чего студия ещё не собрала —
   из профиля, добытого анонимно. Числа студии точнее (их отдаёт сам аккаунт)
   и достаются дешевле, поэтому идут первыми.

   Функция одна на показ и на сортировку: порядок по колонке должен совпадать
   с числом, которое в этой колонке стоит. */

export interface RowNumbers {
  followers: number | null
  posts: number | null
  /** непрочитанные посетители профиля — их знает только студия */
  visitors: number | null
}

export function rowNumbers(account: Account, counters?: StudioCountersMap): RowNumbers {
  const studio = counters?.[account.username]
  const profile = account.profile
  return {
    // ноль — это значение, а не «неизвестно»: подменять его профилем нельзя
    followers: studio?.followers ?? profile?.followers ?? null,
    posts: studio?.posts ?? profile?.posts?.count ?? null,
    visitors: studio?.unread_visitors ?? null,
  }
}
