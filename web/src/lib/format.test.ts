import { describe, expect, it } from "vitest"

import { count, fmtAgo, fmtCompact, fmtDateTime, fmtDec, fmtSigned, fmtSpan, fmtUntil, sentence } from "./format"

const T = " "

describe("fmtDec", () => {
  it("целое без запятой, дробное — ровно два знака", () => {
    expect(fmtDec(44000)).toBe(`44${T}000`)
    expect(fmtDec(5117.5)).toBe(`5${T}117,50`)
  })
  it("округляет по третьему знаку и гасит шум плавающей точки", () => {
    expect(fmtDec(5117.559)).toBe(`5${T}117,56`)
    expect(fmtDec(5117.551)).toBe(`5${T}117,55`)
    expect(fmtDec(15352.68 / 3)).toBe(`5${T}117,56`)
    expect(fmtDec(1.005)).toBe("1,01")
    expect(fmtDec(0.999)).toBe("1")
  })
  it("минус только у ненулевого", () => {
    expect(fmtDec(-2.85)).toBe("−2,85")
    expect(fmtDec(-0.001)).toBe("0")
    expect(fmtSigned(3)).toBe("+3")
  })
})

describe("fmtCompact", () => {
  it("сокращает тысячи и миллионы", () => {
    expect(fmtCompact(950)).toBe("950")
    expect(fmtCompact(1234)).toBe("1,2K")
    expect(fmtCompact(263000)).toBe("263K")
    expect(fmtCompact(2600000)).toBe("2,6M")
    expect(fmtCompact(null)).toBe("—")
  })
  it("округление переносит на ступень выше, а не даёт «1000K»", () => {
    expect(fmtCompact(999950)).toBe("1M")
    expect(fmtCompact(999999999)).toBe("1B")
    expect(fmtCompact(999499)).toBe("999K")
  })
})

describe("даты", () => {
  it("сегодня — часы, иначе дата", () => {
    const now = new Date(2026, 8, 15, 12, 0)
    expect(fmtDateTime(new Date(2026, 8, 15, 9, 5).toISOString(), now)).toBe("09:05")
    expect(fmtDateTime(new Date(2026, 8, 14, 23, 59).toISOString(), now)).toBe("14.09 23:59")
  })
  it("сколько осталось", () => {
    const now = Date.UTC(2026, 8, 15, 12, 0, 0)
    expect(fmtUntil(new Date(now + 2 * 3600e3 + 15 * 60e3).toISOString(), now)).toBe("2 ч 15 мин")
    expect(fmtUntil(new Date(now + 45e3).toISOString(), now)).toBe("45 с")
    expect(fmtUntil(new Date(now - 1).toISOString(), now)).toBe("скоро")
  })
  it("не показывает «1 ч 60 мин»", () => {
    const now = Date.UTC(2026, 8, 15, 12, 0, 0)
    expect(fmtUntil(new Date(now + 3600e3 + 3570e3).toISOString(), now)).toBe("2 ч")
    expect(fmtUntil(new Date(now + 3600e3).toISOString(), now)).toBe("1 ч")
  })
  it("сколько прошло", () => {
    const now = new Date(2026, 8, 15, 12, 0).getTime()
    const ago = (sec: number) => fmtAgo(now / 1000 - sec, now)
    expect(ago(20)).toBe("только что")
    expect(ago(300)).toBe("5 мин назад")
    expect(ago(3 * 3600)).toBe("3 ч назад")
    expect(ago(2 * 86400)).toBe("2 дн назад")
    expect(ago(-60)).toBe("только что")
    // дальше недели счёт в днях уже ничего не говорит — показываем дату
    expect(ago(30 * 86400)).toBe("16.08")
    expect(fmtAgo(null)).toBe("—")
    expect(fmtAgo(0)).toBe("—")
  })
})

describe("тексты", () => {
  it("склоняет", () => {
    expect(count(1, ["пост", "поста", "постов"])).toBe("1 пост")
    expect(count(3, ["пост", "поста", "постов"])).toBe("3 поста")
    expect(count(11, ["пост", "поста", "постов"])).toBe("11 постов")
    expect(count(21, ["пост", "поста", "постов"])).toBe("21 пост")
  })
  it("предложение с точкой", () => {
    expect(sentence("вход не удался")).toBe("Вход не удался.")
    expect(sentence("Готово.")).toBe("Готово.")
  })
})

describe("fmtSpan", () => {
  it("секунды, минуты, часы — без секунд при минутах", () => {
    expect(fmtSpan(40_000)).toBe("40 с")
    expect(fmtSpan(12 * 60_000 + 45_000)).toBe("13 мин")
    expect(fmtSpan(2 * 3_600_000 + 15 * 60_000)).toBe("2 ч 15 мин")
    expect(fmtSpan(3_600_000)).toBe("1 ч")
  })
})
