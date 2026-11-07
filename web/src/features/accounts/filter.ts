import type { Account, BannedAccount, StudioCountersMap } from "@/api/types"

import { rowNumbers } from "./studio"

/* Срезы списка аккаунтов и порядок строк.

   Главный срез — «Готовы»: аккаунты, которыми прямо сейчас можно лить. Всё
   остальное — это списки того, что надо починить: «Без входа» и «В тени».
   «Отключены» (забаненные) живут отдельным срезом и в остальные не попадают
   никогда — в общем списке им делать нечего. */

export type AccountsFilter = "ready" | "all" | "nologin" | "shadow" | "banned"

export function inShadow(a: Account): boolean {
  return (a.profile?.posts?.shadow ?? 0) > 0
}

/** Готов к работе: вход сохранён и постов в тени нет. */
export function isReady(a: Account): boolean {
  return a.has_session && !inShadow(a)
}

export function filterAccounts(accounts: Account[], filter: AccountsFilter): Account[] {
  switch (filter) {
    case "ready":
      return accounts.filter(isReady)
    case "nologin":
      return accounts.filter((a) => !a.has_session)
    case "shadow":
      return accounts.filter(inShadow)
    case "banned":
      return []
    default:
      return accounts
  }
}

/** Поиск по логину и стране: регистр не важен, пустой запрос — всё как есть.
    У страны бывает null (сессии нет) — такие строки просто не совпадают. */
export function searchByName<T extends { username: string; region?: string | null }>(
  items: T[],
  query: string
): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return items
  return items.filter(
    (it) => it.username.toLowerCase().includes(q) || (it.region?.toLowerCase().includes(q) ?? false)
  )
}

export function filterCounts(
  accounts: Account[],
  banned: BannedAccount[]
): Record<AccountsFilter, number> {
  return {
    ready: accounts.filter(isReady).length,
    all: accounts.length,
    nologin: accounts.filter((a) => !a.has_session).length,
    shadow: accounts.filter(inShadow).length,
    banned: banned.length,
  }
}

/* ── порядок строк ───────────────────────────────────────────────────── */

export type SortKey =
  | "name"
  | "region"
  | "followers"
  | "likes"
  | "views"
  | "posts"
  | "shadow"
  | "fetched"
export type SortDir = "asc" | "desc"

/** Число для сортировки; null — «неизвестно», такие строки всегда в конце.
    Источник тот же, что у показа: иначе колонка сортировалась бы не по тому
    числу, которое в ней написано (см. rowNumbers). */
function sortValue(a: Account, key: SortKey, counters?: StudioCountersMap): number | null {
  const p = a.profile
  const numbers = rowNumbers(a, counters)
  switch (key) {
    case "followers":
      return numbers.followers
    case "likes":
      return p?.likes ?? null
    case "views":
      return p?.posts?.views ?? null
    case "posts":
      return numbers.posts
    case "shadow":
      return p?.posts?.shadow ?? null
    case "fetched":
      return p?.fetched_at ?? null
    default:
      return null
  }
}

/* У числовых колонок сразу интересна верхушка, у логина — алфавит: поэтому
   по умолчанию числа идут по убыванию, а логин и страна — по возрастанию
   (страна — код из букв, а не величина, там естественен алфавит). */
export const defaultDir = (key: SortKey): SortDir =>
  key === "name" || key === "region" ? "asc" : "desc"

/* «Неизвестно» не участвует в гонке: такая строка внизу при любом направлении,
   а при равенстве (или паре неизвестных) порядок решает логин. Приём общий и
   для чисел, и для строки страны — отличается только сравнение значений. */
function compareKnown<T>(x: T | null, y: T | null, cmp: (x: T, y: T) => number, sign: number): number | null {
  if (x == null || y == null) {
    if (x == null && y == null) return null
    return x == null ? 1 : -1
  }
  return x === y ? null : cmp(x, y) * sign
}

/** Новый список в заданном порядке; исходный не трогаем. */
export function sortAccounts(
  accounts: Account[],
  key: SortKey,
  dir: SortDir,
  counters?: StudioCountersMap
): Account[] {
  const sign = dir === "asc" ? 1 : -1
  return [...accounts].sort((a, b) => {
    const byName = () => a.username.localeCompare(b.username, "ru")
    if (key === "name") return byName() * sign
    if (key === "region") {
      return compareKnown(a.region, b.region, (x, y) => x.localeCompare(y), sign) ?? byName()
    }
    return (
      compareKnown(sortValue(a, key, counters), sortValue(b, key, counters), (x, y) => x - y, sign) ?? byName()
    )
  })
}
