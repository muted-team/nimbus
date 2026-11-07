import { describe, expect, it } from "vitest"

import type { LogItem } from "@/api/types"

import { filterLogs, logKey } from "./log-filter"

const item = (over: Partial<LogItem>): LogItem => ({ seq: 1, ts: 1_700_000_000, level: "", text: "", ...over })

const EVENTS: LogItem[] = [
  item({ seq: 3, level: "err", account: "katya.moon", text: "вход не удался" }),
  item({ seq: 2, level: "warn", text: "прокси медленно отвечает" }),
  item({ seq: 1, level: "ok", account: "mira", text: "пост опубликован" }),
  item({ seq: 0, level: "err", text: "запрос не вышел", debug: true, source: "publish" }),
]

const ALL = { debug: false, level: "all", search: "" } as const

describe("filterLogs", () => {
  it("подробности скрыты без тумблера и показаны с ним", () => {
    expect(filterLogs(EVENTS, ALL).items).toHaveLength(3)
    expect(filterLogs(EVENTS, { ...ALL, debug: true }).items).toHaveLength(4)
  })

  it("уровень режет список, счётчики — по всему набору без среза уровнем", () => {
    const v = filterLogs(EVENTS, { ...ALL, level: "err" })
    expect(v.items.map((i) => i.seq)).toEqual([3])
    expect(v.counts).toEqual({ all: 3, err: 1, warn: 1 })
    expect(v.total).toBe(3)
  })

  it("поиск — подстрока без учёта регистра по тексту и аккаунту", () => {
    expect(filterLogs(EVENTS, { ...ALL, search: "  ВХОД " }).items.map((i) => i.seq)).toEqual([3])
    expect(filterLogs(EVENTS, { ...ALL, search: "MIRA" }).items.map((i) => i.seq)).toEqual([1])
    expect(filterLogs(EVENTS, { ...ALL, search: "вход" }).counts).toEqual({ all: 1, err: 1, warn: 0 })
  })

  it("пусто из-за фильтров отличается от пустого журнала", () => {
    const filtered = filterLogs(EVENTS, { ...ALL, search: "нет такого" })
    expect(filtered.items).toHaveLength(0)
    expect(filtered.total).toBe(3)
    expect(filterLogs([], ALL).total).toBe(0)
  })
})

describe("logKey", () => {
  it("номер записи сервера, своим записям — локальный индекс", () => {
    expect(logKey(item({ seq: 42 }), 0)).toBe("42")
    expect(logKey(item({ seq: 0 }), 5)).toBe("local-5")
  })
})

describe("filterLogs: журнал одного аккаунта", () => {
  it("оставляет только его записи", () => {
    const v = filterLogs(EVENTS, { ...ALL, account: "mira" })
    expect(v.items.map((i) => i.seq)).toEqual([1])
    expect(v.total).toBe(1)
  })

  it("поиск по @юзернейму находит его записи: собака только для показа", () => {
    expect(filterLogs(EVENTS, { ...ALL, search: "@katya" }).items.map((i) => i.seq)).toEqual([3])
  })
})
