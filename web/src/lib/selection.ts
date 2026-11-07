/* Выбор строк таблицы — одно правило на все списки (аккаунты, прокси):
   solo — только эта строка (повторный клик по единственной снимает выбор),
   toggle — Ctrl и флажок, range — Shift: рамка от последней кликнутой
   строки поверх того, что было выбрано до первого Shift. Чистая функция:
   хранят выбор сами экраны, а считают по ней. */

export type PickMode = "solo" | "toggle" | "range"

export interface SelectionState<K> {
  selected: Set<K>
  /** последняя кликнутая строка — от неё тянется рамка Shift */
  anchor: K | null
  /** выбор до первого Shift-клика: рамка собирается поверх него */
  rangeBase: Set<K> | null
}

export const emptySelection = <K>(): SelectionState<K> => ({ selected: new Set(), anchor: null, rangeBase: null })

/** Следующий выбор после клика по строке `key`; `order` — строки в порядке экрана. */
export function pick<K>(state: SelectionState<K>, key: K, mode: PickMode, order: K[]): SelectionState<K> {
  const { selected } = state
  if (mode === "range") {
    const to = order.indexOf(key)
    if (to < 0) return state
    const base = state.rangeBase ?? new Set(selected)
    const from = state.anchor === null ? 0 : order.indexOf(state.anchor)
    const [a, b] = from < 0 ? [to, to] : [Math.min(from, to), Math.max(from, to)]
    const next = new Set(base)
    for (let i = a; i <= b; i++) next.add(order[i])
    return { selected: next, rangeBase: base, anchor: key }
  }
  if (mode === "toggle") {
    const next = new Set(selected)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return { selected: next, rangeBase: null, anchor: key }
  }
  const solo = selected.has(key) && selected.size === 1
  return { selected: solo ? new Set() : new Set([key]), rangeBase: null, anchor: key }
}

/** Выбор без строк, которых больше нет; тот же объект, если убирать нечего. */
export function prune<K>(state: SelectionState<K>, alive: Iterable<K>): SelectionState<K> {
  const live = new Set(alive)
  let changed = false
  const next = new Set<K>()
  for (const k of state.selected) {
    if (live.has(k)) next.add(k)
    else changed = true
  }
  return changed ? { ...state, selected: next } : state
}
