import type { ProxiesResponse } from "@/api/types"

import { healthCounts, usableProxies } from "./health"

/* Хватит ли прокси на «Потоки» из настроек.

   proxy_pool выдаёт наименее занятый прокси и разрешает нескольким делам идти
   через один адрес — счётчик занятости растёт без предела
   (modules/proxy_pool.py). При потоках больше, чем живых прокси, часть
   аккаунтов пойдёт одновременно через чужой IP, а инструкция просит по одному
   прокси на аккаунт.

   Живым здесь считаем то, что пул отдаёт в работу, — всё, кроме мёртвого
   (см. usableProxies): одна мера с плиткой обзора. Проверяемый сейчас в счёте:
   он тоже идёт в работу, а вердикта у него нет.

   Сколько дел идёт разом — это потоков, но не больше аккаунтов: лишние потоки
   ждут, пока освободится аккаунт. */

export type CapacityKind = "off" | "empty" | "none" | "short" | "ok"

export interface Capacity {
  kind: CapacityKind
  /** потоков из настроек */
  threads: number
  /** прокси, которые пул может позвать в работу */
  alive: number
  /** сколько аккаунтов пойдёт публиковаться разом */
  parallel: number
  /** по скольку аккаунтов придётся на один IP, если прокси не хватает */
  perProxy: number
}

/** Сколько аккаунтов пойдёт в запуск: выделенные, а без выделения — все. Та же
    мера, что у запуска кампании (`features/campaign/launcher.ts`): на выборке
    аккаунтов прокси нужно меньше, и пугать нехваткой, которой не будет, нельзя. */
export function accountsInRun(
  all: readonly { username: string }[],
  selected: ReadonlySet<string>
): number {
  const picked = all.filter((a) => selected.has(a.username)).length
  return picked || all.length
}

/** null — сказать нечего (публиковать некому). */
export function proxyCapacity(
  data: Pick<ProxiesResponse, "proxies" | "enabled" | "health">,
  threads: number,
  accounts: number
): Capacity | null {
  if (accounts <= 0) return null
  const alive = usableProxies(healthCounts(data.health))
  const parallel = Math.min(threads, accounts)
  const perProxy = alive ? Math.ceil(parallel / alive) : parallel
  const base = { threads, alive, parallel, perProxy }
  if (!data.enabled) return { ...base, kind: "off" }
  if (!data.proxies.length) return { ...base, kind: "empty" }
  // пул берёт в работу всё, кроме мёртвого: живых нет — значит мертвы все
  if (!alive) return { ...base, kind: "none" }
  return { ...base, kind: alive < parallel ? "short" : "ok" }
}
