import { describe, expect, it } from "vitest"

import type { LogItem } from "@/api/types"
import { unseenErrors } from "@/api/logs"

import { PAST_LABEL, rowMark } from "./labels"

/* Пометка в строке журнала: подробность называет источник, запись прошлого
   запуска — помечена, свежее событие идёт без пометки. Поднятые из файла
   записи приходят без подробностей, поэтому раньше они выглядели как свежие. */

const item = (extra: Partial<LogItem>): LogItem => ({
  seq: 1,
  ts: 1_800_000_000,
  level: "err",
  text: "вход не удался",
  ...extra,
})

describe("что стоит перед текстом строки", () => {
  it("свежее событие — без пометки", () => {
    expect(rowMark(item({}))).toBeNull()
  })

  it("запись прошлого запуска — помечена", () => {
    expect(rowMark(item({ past: true }))).toEqual({ kind: "past", text: PAST_LABEL })
  })

  it("подробность с источником — как было: источник", () => {
    expect(rowMark(item({ debug: true, source: "login" }))).toEqual({
      kind: "source",
      text: "login",
    })
  })

  it("подробность без источника — без пометки", () => {
    expect(rowMark(item({ debug: true }))).toBeNull()
  })
})

/* Отметка «Журнал» в меню считается по этой же функции. */
describe("сколько ошибок ещё не видели", () => {
  it("записи прошлого запуска не считаются свежими", () => {
    expect(unseenErrors([item({ seq: 3, past: true })], 0)).toBe(0)
  })

  it("ошибка этого запуска считается", () => {
    expect(unseenErrors([item({ seq: 9 })], 3)).toBe(1)
  })

  it("ошибки до отметки просмотра не считаются", () => {
    expect(unseenErrors([item({ seq: 3 }), item({ seq: 2 })], 4)).toBe(0)
  })

  it("подробности не считаются", () => {
    expect(unseenErrors([item({ seq: 9, debug: true })], 3)).toBe(0)
  })

  it("не ошибка не считается", () => {
    expect(unseenErrors([item({ seq: 9, level: "warn" })], 3)).toBe(0)
  })
})
