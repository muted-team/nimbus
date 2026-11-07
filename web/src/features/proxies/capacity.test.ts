import { describe, expect, it } from "vitest"

import type { ProxiesResponse, ProxyHealth, ProxyState } from "@/api/types"

import { accountsInRun, proxyCapacity } from "./capacity"
import { capacityText } from "./labels"

/* Порог: разом публикуется не больше, чем потоков и чем аккаунтов, — столько
   же прокси и нужно. Один прокси на несколько одновременных дел означает чужой
   IP для части аккаунтов, а инструкция просит по прокси на аккаунт. */

const health = (...states: ProxyState[]): ProxyHealth[] =>
  states.map((state, i) => ({ proxy: `host${i}:1080`, state }))

const data = (patch: Partial<ProxiesResponse> = {}): ProxiesResponse => ({
  proxies: ["host0:1080", "host1:1080"],
  enabled: true,
  rotating: 0,
  health: health("ok", "ok"),
  ...patch,
})

describe("хватит ли прокси на потоки", () => {
  it("прокси выключены: все аккаунты пойдут с вашего IP", () => {
    const cap = proxyCapacity(data({ enabled: false }), 5, 50)
    expect(cap?.kind).toBe("off")
    expect(capacityText(cap!)).toBe("Прокси выключены — все аккаунты пойдут с вашего IP.")
  })

  it("список пуст: то же самое, но по другой причине", () => {
    const cap = proxyCapacity(data({ proxies: [], health: [] }), 5, 50)
    expect(cap?.kind).toBe("empty")
    expect(capacityText(cap!)).toBe("Список прокси пуст — все аккаунты пойдут с вашего IP.")
  })

  it("живых меньше потоков и аккаунтов: говорим, по скольку сядет на IP", () => {
    const cap = proxyCapacity(data({ health: health("ok", "ok", "dead") }), 5, 50)
    expect(cap).toMatchObject({ kind: "short", alive: 2, parallel: 5, perProxy: 3 })
    expect(capacityText(cap!)).toBe(
      "Потоков 5, живых прокси 2 — по 3 аккаунта на один IP."
    )
  })

  it("потоков больше, чем аккаунтов: лишние ждут, прокси хватает", () => {
    const cap = proxyCapacity(data({ health: health("ok", "ok") }), 8, 2)
    expect(cap).toMatchObject({ kind: "ok", parallel: 2, perProxy: 1 })
  })

  it("прокси не больше числа аккаунтов и потоков — хватает, не пугаем", () => {
    const cap = proxyCapacity(data({ health: health("ok", "ok", "ok") }), 3, 10)
    expect(cap?.kind).toBe("ok")
    expect(capacityText(cap!)).toBe("Потоков 3, живых прокси 3 — хватает.")
  })

  it("поровну потоков и живых прокси — хватает", () => {
    expect(proxyCapacity(data({ health: health("ok", "ok") }), 2, 9)?.kind).toBe("ok")
  })

  it("непроверенные считаются рабочими: пул их отдаёт", () => {
    expect(proxyCapacity(data({ health: health("unknown", "unknown") }), 2, 9)?.kind).toBe(
      "ok"
    )
  })

  it("проверяемый сейчас идёт в работу наравне с проверенным", () => {
    const cap = proxyCapacity(data({ health: health("ok", "checking") }), 1, 9)
    expect(cap).toMatchObject({ kind: "ok", alive: 2 })
  })

  it("идёт проверка, вердиктов нет — всё равно считаем живыми", () => {
    const cap = proxyCapacity(data({ health: health("checking", "checking") }), 2, 9)
    expect(cap).toMatchObject({ kind: "ok", alive: 2 })
  })

  it("все мертвы — публикация не пойдёт", () => {
    const cap = proxyCapacity(data({ health: health("dead", "dead") }), 2, 9)
    expect(cap?.kind).toBe("none")
    expect(capacityText(cap!)).toBe("Живых прокси нет — публикация не пойдёт.")
  })

  it("аккаунтов нет — считать нечего", () => {
    expect(proxyCapacity(data(), 5, 0)).toBeNull()
  })

  it("сколько аккаунтов сядет на IP — по числу потоков, а не строк списка", () => {
    const cap = proxyCapacity(data({ health: health("ok", "ok", "ok") }), 8, 8)
    expect(cap).toMatchObject({ kind: "short", perProxy: 3 })
  })
})

/* На выборке аккаунтов прокси нужно меньше: кампания возьмёт выделенные строки,
   а без выделения — весь список (features/campaign/launcher.ts). */

describe("сколько аккаунтов пойдёт в запуск", () => {
  const all = [{ username: "a" }, { username: "b" }, { username: "c" }]

  it("выделения нет — весь список", () => {
    expect(accountsInRun(all, new Set())).toBe(3)
  })

  it("выделены двое — их и считаем", () => {
    expect(accountsInRun(all, new Set(["a", "c"]))).toBe(2)
  })

  it("в выделении чужое имя — считаем только тех, кто есть в списке", () => {
    expect(accountsInRun(all, new Set(["b", "нет такого"]))).toBe(1)
  })

  it("выделено всё — как без выделения", () => {
    expect(accountsInRun(all, new Set(["a", "b", "c"]))).toBe(3)
  })

  it("списка нет — считать нечего", () => {
    expect(accountsInRun([], new Set(["a"]))).toBe(0)
  })
})
