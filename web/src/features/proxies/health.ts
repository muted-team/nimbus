import type { ProxyHealth, ProxyState } from "@/api/types"

/* Отметки проверки прокси одним счётом — и для сводки публикации, и для строки
   «хватит ли прокси на потоки», и для свежести в списке.

   Живым считаем того, кого пул берёт в работу: всё, кроме мёртвого
   (`modules/proxy_pool.py`: `_usable` отсеивает только `state == "dead"`).
   Проверяемый сейчас — надпись для интерфейса: `_mark` подменяет состояние,
   пока адрес в `_checking`, а само `entry["state"]` меняется лишь по итогу
   проверки, — значит он уходит в работу наравне с непроверенным. */

export interface HealthCounts {
  ok: number
  dead: number
  unknown: number
  checking: number
  /** ни одного вердикта ещё нет: показывать «живых 0» было бы неправдой */
  unchecked: boolean
}

export function healthCounts(health: ProxyHealth[]): HealthCounts {
  const n = (state: ProxyState) => health.filter((h) => h.state === state).length
  const counts = { ok: n("ok"), dead: n("dead"), unknown: n("unknown"), checking: n("checking") }
  return { ...counts, unchecked: counts.ok + counts.dead + counts.checking === 0 }
}

/** Сколько прокси пул может позвать в работу: все, кроме мёртвых. */
export const usableProxies = (c: HealthCounts) => c.ok + c.unknown + c.checking

/* --- свежесть и смена IP --------------------------------------------------- */

/** Окно свежести вердикта, секунды: старше — пул берётся за строку сам.
    Одно число и одно имя с `AUTO_CHECK_SEC` в `modules/proxy_pool.py`; тамошний
    `STALE_SEC` (20 с) — другое, это свежесть вердикта «мёртв». */
export const AUTO_CHECK_SEC = 300

/** Число из ответа сервера: null — пришло не число (строка, NaN, ничего).
    Отметка времени не должна превращаться в «NaN» на экране. */
export function serverNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

/** Строку надо проверить: вердикта ещё нет или он старше окна. Проверяемую
    сейчас не трогаем — она уже в работе. Нечитаемую отметку считаем отсутствием
    вердикта: проверить лишний раз дешевле, чем показать неправду. */
export function needsCheck(h: ProxyHealth, now = Date.now()): boolean {
  if (h.state === "checking") return false
  const checked = serverNumber(h.checked_at)
  if (checked == null) return true
  return now - checked * 1000 >= AUTO_CHECK_SEC * 1000
}

/** Есть ли что проверять: хоть одна строка без вердикта или устаревшая. */
export const dueForCheck = (health: ProxyHealth[], now = Date.now()) =>
  health.some((h) => needsCheck(h, now))

/** Повтор авто-запроса проверки не чаще раза в минуту: раздел открывают и
    закрывают сколько угодно раз. */
export const AUTO_CHECK_MIN_MS = 60_000

/** Звать ли проверку при открытии раздела. */
export function autoCheckAllowed(
  health: ProxyHealth[],
  lastAt: number | null,
  now = Date.now()
): boolean {
  if (!dueForCheck(health, now)) return false
  return lastAt == null || now - lastAt >= AUTO_CHECK_MIN_MS
}

/** Секунд до смены IP у строки: `rotate_in` — на момент снимка, поэтому
    вычитаем прошедшее с него. 0 — можно сейчас. */
export const rotateLeft = (h: ProxyHealth, elapsedSec = 0) =>
  Math.max(0, (serverNumber(h.rotate_in) ?? 0) - Math.max(0, elapsedSec))

/** Можно ли сменить IP: у строки есть ссылка и ждать нечего. */
export const canRotate = (h: ProxyHealth, elapsedSec = 0) =>
  !!h.rotating && rotateLeft(h, elapsedSec) === 0

/** Как часто обновлять время на экране, мс. Снимок приходит раз в минуту, а
    подписи «проверено N мин назад» и «проверка через N мин» должны расти, пока
    раздел открыт, — значит свой таймер нужен всегда, а не только при отсчётах.
    Секунды достаются идущим отсчётам (смена IP, проверка), а минутам и
    тридцати секунд хватает: раз в секунду перерисовывать сотню строк незачем. */
export const nowTickMs = (health: ProxyHealth[]) =>
  health.some((h) => h.rotate_in || h.next_check_at) ? 1000 : 30_000
