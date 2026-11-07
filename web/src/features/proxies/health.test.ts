import { describe, expect, it } from "vitest"

import type { ProxyHealth, ProxyState } from "@/api/types"

import {
  AUTO_CHECK_SEC,
  autoCheckAllowed,
  canRotate,
  dueForCheck,
  healthCounts,
  needsCheck,
  nowTickMs,
  rotateLeft,
  serverNumber,
  usableProxies,
} from "./health"

/* Один счёт отметок на плитку обзора и на строку «хватит ли прокси»: две
   разные мерки одного слова разошлись бы на глазах у человека. Живым считается
   всё, кроме мёртвого, — ровно то, что пул берёт в работу. */

const health = (...states: ProxyState[]): ProxyHealth[] =>
  states.map((state, i) => ({ proxy: `host${i}:1080`, state }))

const row = (patch: Partial<ProxyHealth>): ProxyHealth => ({
  proxy: "host:1080",
  state: "ok",
  ...patch,
})

describe("счёт отметок проверки", () => {
  it("считает по состояниям", () => {
    expect(healthCounts(health("ok", "ok", "dead", "checking", "unknown"))).toEqual({
      ok: 2,
      dead: 1,
      unknown: 1,
      checking: 1,
      unchecked: false,
    })
  })

  it("непроверенный список — вердиктов нет", () => {
    expect(healthCounts(health("unknown", "unknown")).unchecked).toBe(true)
  })

  it("идёт проверка — это уже вердикт, а не «не проверяли»", () => {
    expect(healthCounts(health("checking")).unchecked).toBe(false)
  })

  it("пустой список — вердиктов нет", () => {
    expect(healthCounts([]).unchecked).toBe(true)
  })

  it("в работу пул берёт всех, кроме мёртвых", () => {
    expect(usableProxies(healthCounts(health("ok", "unknown", "dead", "checking")))).toBe(3)
  })

  it("проверяемый сейчас в работе наравне с непроверенным", () => {
    expect(usableProxies(healthCounts(health("checking", "checking")))).toBe(2)
  })
})

describe("свежесть отметки", () => {
  const now = 1_800_000_000_000

  it("вердикта нет — проверять", () => {
    expect(needsCheck(row({ state: "unknown", checked_at: null }), now)).toBe(true)
  })

  it("проверяемую сейчас второй раз не зовём", () => {
    expect(needsCheck(row({ state: "checking", checked_at: null }), now)).toBe(false)
  })

  it("свежая отметка — ждём", () => {
    expect(needsCheck(row({ checked_at: 1_800_000_000 - 10 }), now)).toBe(false)
  })

  it("отметка старше окна — проверять", () => {
    expect(needsCheck(row({ checked_at: 1_800_000_000 - AUTO_CHECK_SEC }), now)).toBe(true)
  })

  it("отметку не прочитать — считаем, что вердикта нет", () => {
    const broken = { checked_at: "2026-09-17T01:00:00Z" } as unknown as Partial<ProxyHealth>
    expect(needsCheck(row(broken), now)).toBe(true)
  })

  it("число из ответа берём только настоящее", () => {
    expect(serverNumber(1_800_000_000)).toBe(1_800_000_000)
    expect(serverNumber(0)).toBe(0)
    expect(serverNumber(null)).toBeNull()
    expect(serverNumber(Number.NaN)).toBeNull()
    expect(serverNumber("1.5")).toBeNull()
  })

  it("есть что проверять — только тогда и зовём", () => {
    const rows = [row({ checked_at: 1_800_000_000 - 10 }), row({ state: "unknown" })]
    expect(dueForCheck(rows, now)).toBe(true)
    expect(dueForCheck([row({ checked_at: 1_800_000_000 - 10 })], now)).toBe(false)
  })
})

describe("авто-проверка при открытии раздела", () => {
  const now = 1_800_000_000_000
  const stale = [row({ state: "unknown", checked_at: null })]

  it("первое открытие — зовём", () => {
    expect(autoCheckAllowed(stale, null, now)).toBe(true)
  })

  it("недавно звали — молчим, чтобы не долбить сервер", () => {
    expect(autoCheckAllowed(stale, now - 10_000, now)).toBe(false)
  })

  it("минута прошла — снова можно", () => {
    expect(autoCheckAllowed(stale, now - 61_000, now)).toBe(true)
  })

  it("проверять нечего — не зовём, сколько ни открывай", () => {
    expect(autoCheckAllowed([row({ checked_at: now / 1000 - 10 })], null, now)).toBe(false)
  })
})

describe("смена IP", () => {
  it("ссылки нет — менять нечего", () => {
    expect(canRotate(row({}))).toBe(false)
  })

  it("ссылка есть, ждать нечего — можно", () => {
    expect(canRotate(row({ rotating: true, rotate_in: 0 }))).toBe(true)
  })

  it("кулдаун идёт — нельзя, но отсчёт кончается", () => {
    const h = row({ rotating: true, rotate_in: 40 })
    expect(canRotate(h, 0)).toBe(false)
    expect(rotateLeft(h, 0)).toBe(40)
    expect(rotateLeft(h, 25)).toBe(15)
    expect(canRotate(h, 40)).toBe(true)
    expect(rotateLeft(h, 90)).toBe(0)
  })
})

describe("часы на экране", () => {
  it("идущий отсчёт — секунда в секунду", () => {
    expect(nowTickMs([row({ rotating: true, rotate_in: 40 })])).toBe(1000)
    expect(nowTickMs([row({ next_check_at: 1_800_000_000 })])).toBe(1000)
  })

  it("одни минуты «проверено N мин назад» — тикаем и без отсчётов", () => {
    expect(nowTickMs([row({ checked_at: 1_800_000_000 })])).toBe(30_000)
    expect(nowTickMs([])).toBe(30_000)
  })
})
