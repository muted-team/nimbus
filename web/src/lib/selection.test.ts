import { describe, expect, it } from "vitest"

import { emptySelection, pick, prune } from "./selection"

/* Выбор строк одинаков у аккаунтов и прокси: флажок и Ctrl добавляют и
   убирают, Shift тянет рамку от последней кликнутой строки поверх выбора,
   сделанного до первого Shift. */

const ORDER = ["a", "b", "c", "d", "e"]

describe("pick", () => {
  it("toggle добавляет и убирает", () => {
    let s = pick(emptySelection<string>(), "b", "toggle", ORDER)
    s = pick(s, "d", "toggle", ORDER)
    expect([...s.selected]).toEqual(["b", "d"])
    s = pick(s, "b", "toggle", ORDER)
    expect([...s.selected]).toEqual(["d"])
  })

  it("range — от последней кликнутой поверх выбора до первого Shift", () => {
    let s = pick(emptySelection<string>(), "a", "toggle", ORDER)
    s = pick(s, "c", "range", ORDER)
    expect([...s.selected].sort()).toEqual(["a", "b", "c"])
    s = pick(s, "e", "range", ORDER)
    expect([...s.selected].sort()).toEqual(["a", "c", "d", "e"])
  })

  it("solo по единственной выбранной снимает выбор", () => {
    const s = pick(emptySelection<string>(), "c", "solo", ORDER)
    expect([...s.selected]).toEqual(["c"])
    expect(pick(s, "c", "solo", ORDER).selected.size).toBe(0)
  })
})

describe("prune", () => {
  it("убирает исчезнувшие строки и не трогает выбор, если убирать нечего", () => {
    const s = pick(pick(emptySelection<number>(), 1, "toggle", [1, 2]), 2, "toggle", [1, 2])
    expect([...prune(s, [2]).selected]).toEqual([2])
    expect(prune(s, [1, 2])).toBe(s)
  })
})
