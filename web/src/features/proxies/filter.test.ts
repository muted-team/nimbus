import { describe, expect, it } from "vitest"

import type { ProxyHealth, ProxyState } from "@/api/types"

import {
  defaultDir,
  filterCounts,
  filterProxies,
  loginIndexes,
  offIndexes,
  publishIndexes,
  searchProxies,
  sortProxies,
  toProxyRows,
  type ProxyRow,
} from "./filter"

/* У пачки прокси одного провайдера адрес совпадает — единственное, что
   различает строки, это их номер в исходном списке. Он же уходит в
   POST /api/proxies/rotate: сортировка и фильтр не должны его подменить. */

const health = (...states: ProxyState[]): ProxyHealth[] =>
  states.map((state, i) => ({ proxy: `host${i}:1080`, state }))

describe("модель строки", () => {
  it("номер строки — это позиция в исходном списке, а не в отфильтрованном", () => {
    const rows = toProxyRows(health("dead", "ok", "ok"))
    expect(rows.map((r) => r.index)).toEqual([0, 1, 2])
  })

  it("сортировка не путает номер строки: у одинаковых адресов он различает их", () => {
    const same: ProxyHealth[] = [
      { proxy: "proxy.noshadow.pro:9696", state: "ok", ping: 50 },
      { proxy: "proxy.noshadow.pro:9696", state: "ok", ping: 10 },
    ]
    const rows = toProxyRows(same)
    const sorted = sortProxies(rows, "ping", "asc")
    // после сортировки по пингу впереди должна идти именно вторая исходная
    // строка (index 1, пинг 10) — адрес у обеих один и тот же
    expect(sorted.map((r) => r.index)).toEqual([1, 0])
  })

  it("сортировка не трогает исходный список", () => {
    const rows = toProxyRows(health("dead", "ok"))
    sortProxies(rows, "index", "desc")
    expect(rows.map((r) => r.index)).toEqual([0, 1])
  })
})

describe("срезы", () => {
  const rows = toProxyRows(health("ok", "ok", "dead", "checking", "unknown"))

  it("живые — все, кроме мёртвых", () => {
    expect(filterProxies(rows, "alive").map((r) => r.index)).toEqual([0, 1, 3, 4])
  })

  it("все — весь список", () => {
    expect(filterProxies(rows, "all")).toHaveLength(5)
  })

  it("мёртвые", () => {
    expect(filterProxies(rows, "dead").map((r) => r.index)).toEqual([2])
  })

  it("не проверены — только unknown, идущая проверка это не «не проверен»", () => {
    expect(filterProxies(rows, "unchecked").map((r) => r.index)).toEqual([4])
  })

  it("счётчики совпадают со срезами", () => {
    expect(filterCounts(rows)).toEqual({ alive: 4, all: 5, dead: 1, unchecked: 1 })
  })
})

describe("поиск по адресу и стране", () => {
  const rows: ProxyRow[] = toProxyRows([
    { proxy: "1.2.3.4:1080", state: "ok", country: "US" },
    { proxy: "5.6.7.8:1080", state: "ok", country: "DE" },
    { proxy: "9.9.9.9:1080", state: "ok", country: null },
  ])

  it("регистр и часть адреса не важны", () => {
    expect(searchProxies(rows, "1.2.3").map((r) => r.proxy)).toEqual(["1.2.3.4:1080"])
  })

  it("совпадает и по коду страны", () => {
    expect(searchProxies(rows, "de").map((r) => r.proxy)).toEqual(["5.6.7.8:1080"])
  })

  it("страны не знаем — запрос по коду просто не совпадает, это не ошибка", () => {
    expect(searchProxies(rows, "us").map((r) => r.proxy)).toEqual(["1.2.3.4:1080"])
  })

  it("пустой запрос — весь список", () => {
    expect(searchProxies(rows, "  ")).toHaveLength(3)
  })
})

describe("порядок строк", () => {
  it("по умолчанию номер и адрес — по возрастанию, числа — по убыванию", () => {
    expect(defaultDir("index")).toBe("asc")
    expect(defaultDir("proxy")).toBe("asc")
    expect(defaultDir("ping")).toBe("desc")
  })

  it("«неизвестно» всегда внизу, числа сверху", () => {
    const rows = toProxyRows([
      { proxy: "a", state: "ok", ping: null },
      { proxy: "b", state: "ok", ping: 5 },
      { proxy: "c", state: "ok", ping: 50 },
    ])
    expect(sortProxies(rows, "ping", "desc").map((r) => r.proxy)).toEqual(["c", "b", "a"])
    expect(sortProxies(rows, "ping", "asc").map((r) => r.proxy)).toEqual(["b", "c", "a"])
  })

  it("страна — по алфавиту кода, «не знаем» всегда внизу", () => {
    const rows = toProxyRows([
      { proxy: "noknown", state: "ok", country: null },
      { proxy: "de", state: "ok", country: "DE" },
      { proxy: "us", state: "ok", country: "US" },
    ])
    expect(sortProxies(rows, "country", "asc").map((r) => r.proxy)).toEqual(["de", "us", "noknown"])
    expect(sortProxies(rows, "country", "desc").map((r) => r.proxy)).toEqual(["us", "de", "noknown"])
  })

  it("сортировка по стране не путает номер строки", () => {
    const same: ProxyHealth[] = [
      { proxy: "proxy.noshadow.pro:9696", state: "ok", country: "US" },
      { proxy: "proxy.noshadow.pro:9696", state: "ok", country: "DE" },
    ]
    const rows = toProxyRows(same)
    expect(sortProxies(rows, "country", "asc").map((r) => r.index)).toEqual([1, 0])
  })
})

/* Отметки «вход» и «выключена» уходят номерами исходных строк — той же
   ловушки, что уже закрыта для смены IP: экран показывает отфильтрованный и
   отсортированный порядок, а номер строки должен остаться от исходного
   списка независимо от того, что видно на экране сейчас. */
describe("номера строк для групп и выключения", () => {
  const rows = toProxyRows([
    { proxy: "a", state: "dead", login: true, publish: true },
    { proxy: "b", state: "ok", login: false, publish: true, enabled: false },
    { proxy: "c", state: "ok", login: true, publish: false },
  ])

  it("вход — номера отмеченных строк по исходному списку", () => {
    expect(loginIndexes(rows)).toEqual([0, 2])
  })

  it("выключенные — номера по исходному списку", () => {
    expect(offIndexes(rows)).toEqual([1])
  })

  it("публикация — независимая группа, которая может пересекаться со входом", () => {
    expect(publishIndexes(rows)).toEqual([0, 1])
  })

  it("срез и сортировка экрана не меняют номера строк в отметках", () => {
    const screenOrder = sortProxies(filterProxies(rows, "alive"), "proxy", "desc")
    // на экране порядок и состав другие, а номера отметок считаются по
    // исходному списку целиком — не по тому, что сейчас видно
    expect(screenOrder.map((r) => r.index)).toEqual([2, 1])
    expect(loginIndexes(rows)).toEqual([0, 2])
    expect(publishIndexes(rows)).toEqual([0, 1])
    expect(offIndexes(rows)).toEqual([1])
  })
})
