import { describe, expect, it } from "vitest"

import { indexesAfterRemoval, proxiesTextToSave } from "./proxies-store"

/* T-201 (dev/_probe_proxy_wipe.py): открытие раздела не должно стирать
   список. Раньше пустой текст мог улететь сам — здесь единственная дверь для
   пустоты — явное действие человека «удалить последнюю строку». */

describe("что уйдёт на сервер", () => {
  it("пустой список без явного действия — не уходит вовсе", () => {
    expect(proxiesTextToSave([], false)).toBeNull()
  })

  it("пустой список по «удалить последнюю строку» — уходит пустой строкой", () => {
    expect(proxiesTextToSave([], true)).toBe("")
  })

  it("непустой список уходит всегда, независимо от allowEmpty", () => {
    expect(proxiesTextToSave(["a", "b"], false)).toBe("a\nb")
    expect(proxiesTextToSave(["a", "b"], true)).toBe("a\nb")
  })
})

describe("отметки после удаления строки", () => {
  it("снимает отметку удалённой строки и сдвигает только правые", () => {
    expect(indexesAfterRemoval([0, 2, 4], 2)).toEqual([0, 3])
  })

  it("не меняет индексы слева от удалённой строки", () => {
    expect(indexesAfterRemoval([0, 1], 3)).toEqual([0, 1])
  })
})
