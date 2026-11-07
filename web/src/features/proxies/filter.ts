import type { ProxyHealth } from "@/api/types"

import { serverNumber } from "./health"
import { readNoshadow } from "./noshadow"

/* Срез, поиск и порядок строк таблицы прокси.

   Ключ строки — номер в исходном списке (`index`), а не адрес: у пачки от
   одного провайдера адрес совпадает (владелец сейчас держит две прокси на
   одном `proxy.noshadow.pro:9696`, различаются только учётками), и по адресу
   строки не различить. Смена IP, правка, отметки «вход»/«выключена» идут по
   этому номеру (`POST /api/proxies/rotate`, `PUT /api/proxies` с `login`/`off`
   номерами строк), поэтому он несётся в модели строки явно и переживает любую
   сортировку и фильтр — восстанавливать его по позиции после них уже поздно. */

export interface ProxyRow extends ProxyHealth {
  /** номер строки в исходном списке (`data.proxies`/`data.health`); по нему
      идёт смена IP, правка, отметки групп и «выключена» */
  index: number
  /** строка noshadow: страна из логина и сколько минут держится IP (0 —
      ротация); null — не noshadow. Учётку в строку таблицы не несём. */
  noshadow: { country: string; minutes: number } | null
}

/** lines — полные строки списка (`data.proxies`) в том же порядке: из них
    читается режим noshadow. */
export function toProxyRows(health: ProxyHealth[], lines: string[] = []): ProxyRow[] {
  return health.map((h, index) => {
    const n = lines[index] ? readNoshadow(lines[index]) : null
    return { ...h, index, noshadow: n && { country: n.country, minutes: n.minutes } }
  })
}

/** Строка не выключена: поля нет — считаем включённой (сервер молчит про
    «не трогай», а не про «выключи»). */
export const isEnabled = (row: Pick<ProxyHealth, "enabled">) => row.enabled !== false

/* ── срезы ────────────────────────────────────────────────────────────── */

export type ProxiesFilter = "alive" | "all" | "dead" | "unchecked"

/** Живой — всё, кроме мёртвого: та же мера, что у плитки «хватит ли прокси»
    (см. health.ts: usableProxies) — пул берёт в работу именно таких. */
export const isAlive = (row: Pick<ProxyHealth, "state">) => row.state !== "dead"

export function filterProxies(rows: ProxyRow[], filter: ProxiesFilter): ProxyRow[] {
  switch (filter) {
    case "alive":
      return rows.filter(isAlive)
    case "dead":
      return rows.filter((r) => r.state === "dead")
    case "unchecked":
      return rows.filter((r) => r.state === "unknown")
    default:
      return rows
  }
}

export function filterCounts(rows: ProxyRow[]): Record<ProxiesFilter, number> {
  return {
    alive: rows.filter(isAlive).length,
    all: rows.length,
    dead: rows.filter((r) => r.state === "dead").length,
    unchecked: rows.filter((r) => r.state === "unknown").length,
  }
}

/** Поиск по адресу и стране (в `health.proxy` учёток нет — искать больше
    нечему). У страны бывает null (её ещё не спрашивали) — такие строки просто
    не совпадают. */
export function searchProxies(rows: ProxyRow[], query: string): ProxyRow[] {
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(
    (r) => r.proxy.toLowerCase().includes(q) || (r.country?.toLowerCase().includes(q) ?? false)
  )
}

/** Номера строк (`index`), отмеченных для входа, по всему списку — не только
    видимому срезу: отметка «вход» решает не там же, где фильтр экрана. */
export const loginIndexes = (rows: ProxyRow[]) => rows.filter((r) => r.login).map((r) => r.index)

/** Номера строк, отмеченных для публикации. */
export const publishIndexes = (rows: ProxyRow[]) => rows.filter((r) => r.publish).map((r) => r.index)

/** Номера выключенных строк по всему списку — тот же приём, что у `login`. */
export const offIndexes = (rows: ProxyRow[]) => rows.filter((r) => !isEnabled(r)).map((r) => r.index)

/* ── порядок строк ───────────────────────────────────────────────────── */

export type SortKey = "index" | "proxy" | "country" | "ping" | "ms" | "busy" | "checked_at"
export type SortDir = "asc" | "desc"

/** У номера строки, адреса и страны естественен обычный порядок (по
    возрастанию — страна алфавитом, не величиной); у чисел сразу интересна
    верхушка — быстрые, занятые, свежие. */
export const defaultDir = (key: SortKey): SortDir =>
  key === "index" || key === "proxy" || key === "country" ? "asc" : "desc"

function numericValue(row: ProxyRow, key: SortKey): number | null {
  switch (key) {
    case "ping":
      return serverNumber(row.ping)
    case "ms":
      return serverNumber(row.ms)
    case "busy":
      return serverNumber(row.busy)
    case "checked_at":
      return serverNumber(row.checked_at)
    default:
      return null
  }
}

/* «Неизвестно» не участвует в гонке: такая строка внизу при любом направлении,
   а порядок при равенстве (или паре неизвестных) решает номер строки. Приём
   общий для чисел и для кода страны — отличается только сравнение значений. */
function compareKnown<T>(
  x: T | null,
  y: T | null,
  cmp: (x: T, y: T) => number,
  sign: number
): number | null {
  if (x == null || y == null) {
    if (x == null && y == null) return null
    return x == null ? 1 : -1
  }
  return x === y ? null : cmp(x, y) * sign
}

/** Новый список в заданном порядке; исходный не трогаем. */
export function sortProxies(rows: ProxyRow[], key: SortKey, dir: SortDir): ProxyRow[] {
  const sign = dir === "asc" ? 1 : -1
  return [...rows].sort((a, b) => {
    const byIndex = () => a.index - b.index
    if (key === "index") return byIndex() * sign
    if (key === "proxy") {
      return a.proxy === b.proxy ? byIndex() : a.proxy.localeCompare(b.proxy) * sign
    }
    if (key === "country") {
      return (
        compareKnown(a.country ?? null, b.country ?? null, (x, y) => x.localeCompare(y), sign) ??
        byIndex()
      )
    }
    return compareKnown(numericValue(a, key), numericValue(b, key), (x, y) => x - y, sign) ?? byIndex()
  })
}
