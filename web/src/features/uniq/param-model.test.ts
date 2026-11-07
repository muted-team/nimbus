import { describe, expect, it } from "vitest"

import { UNIQ_KEYS, type UniqParam, type UniqSettings } from "@/api/types"

import { applyPatch, numToField, parseClamped, pickParams, previewSignature, sliderValues, snap } from "./param-model"

const P = (min: number, max: number, locked = false, enabled = true): UniqParam => ({
  enabled,
  locked,
  min,
  max,
})

describe("parseClamped", () => {
  it("зажимает в пределы сервера", () => {
    expect(parseClamped("5000", [-360, 360])).toBe(360)
    expect(parseClamped("-5000", [-360, 360])).toBe(-360)
    expect(parseClamped("12", [1, 100])).toBe(12)
  })
  it("пусто и мусор -> null", () => {
    expect(parseClamped("", [0, 10])).toBeNull()
    expect(parseClamped("-", [0, 10])).toBeNull()
    expect(parseClamped("1.2.3", [0, 10])).toBeNull()
  })
  it("запятая и точка — одно и то же", () => {
    expect(parseClamped("1,5", [0, 10])).toBe(1.5)
    expect(parseClamped("1.5", [0, 10])).toBe(1.5)
  })
})

describe("numToField и snap", () => {
  it("поле без разрядов, дробь — запятой", () => {
    expect(numToField(-10, false)).toBe("-10")
    expect(numToField(1.05, true)).toBe("1,05")
    expect(numToField(0.3, true)).toBe("0,3")
  })
  it("шаг гасит шум плавающей точки", () => {
    expect(snap(0.30000000000000004, 0.01)).toBe(0.3)
    expect(snap(5.5, 1)).toBe(6)
    expect(snap(-2.5, 1)).toBe(-2)
  })
})

describe("applyPatch — вилка", () => {
  it("двинутая граница тянет вторую за собой", () => {
    expect(applyPatch(P(-10, 10), { min: 20 })).toEqual(P(20, 20))
    expect(applyPatch(P(-10, 10), { max: -20 })).toEqual(P(-20, -20))
  })
  it("обычная правка вторую границу не трогает", () => {
    expect(applyPatch(P(-10, 10), { min: -5 })).toEqual(P(-5, 10))
    expect(applyPatch(P(-10, 10), { max: 5 })).toEqual(P(-10, 5))
    expect(applyPatch(P(-10, 10), { min: -5, max: 5 })).toEqual(P(-5, 5))
  })
})

describe("applyPatch — замок", () => {
  it("включение приравнивает «до» к «от»", () => {
    expect(applyPatch(P(-10, 10), { locked: true })).toEqual(P(-10, -10, true))
  })
  it("правка «от» при замке тянет «до»", () => {
    expect(applyPatch(P(-10, -10, true), { min: 5 })).toEqual(P(5, 5, true))
  })
  it("выключение меняет только доступность", () => {
    expect(applyPatch(P(-10, -10, true), { locked: false })).toEqual(P(-10, -10, false))
  })
  it("включение параметра значения не трогает", () => {
    expect(applyPatch(P(-10, 10, false, false), { enabled: true })).toEqual(P(-10, 10, false, true))
  })
})

describe("sliderValues", () => {
  it("при замке один бегунок, при вилке два", () => {
    expect(sliderValues(P(5, 5, true))).toEqual([5])
    expect(sliderValues(P(-10, 10))).toEqual([-10, 10])
  })
})

describe("pickParams", () => {
  it("забирает параметры целиком, без мастера и пределов", () => {
    const p = pickParams(fixture())
    expect(Object.keys(p).sort()).toEqual([...UNIQ_KEYS].sort())
    expect(p.rotate).toEqual({ enabled: true, locked: false, min: -10, max: 10 })
  })
  it("замок с разошедшейся вилкой приводит к одному значению", () => {
    const p = pickParams(fixture())
    expect(p.compress).toEqual({ enabled: true, locked: true, min: 80, max: 80 })
    expect(p.hue).toEqual({ enabled: true, locked: true, min: -20, max: -20 })
  })
})

describe("previewSignature", () => {
  it("меняется от папок, мастера, включённости и границ", () => {
    const base = previewSignature(["a"], fixture())
    expect(previewSignature(["a"], fixture())).toBe(base)
    expect(previewSignature(["b"], fixture())).not.toBe(base)
    expect(previewSignature(["a"], fixture({ enabled: false }))).not.toBe(base)
    expect(previewSignature(["a"], fixture({ rotate: { min: -5 } }))).not.toBe(base)
    expect(previewSignature(["a"], fixture({ rotate: { enabled: false } }))).not.toBe(base)
  })
  it("замок без смены значений подпись не меняет", () => {
    const a = fixture()
    const b = fixture()
    b.rotate.locked = true
    expect(previewSignature(["a"], a)).toBe(previewSignature(["a"], b))
  })
})

/* ── данные ─────────────────────────────────────────────────────────── */

function fixture(over: { enabled?: boolean; rotate?: Partial<UniqParam> } = {}): UniqSettings {
  return {
    enabled: over.enabled ?? true,
    limits: {
      rotate: [-360, 360],
      scale: [0, 100],
      compress: [1, 100],
      brightness: [-100, 100],
      contrast: [-100, 100],
      saturation: [-100, 100],
      gamma: [-100, 100],
      hue: [-180, 180],
    },
    rotate: { enabled: true, locked: false, min: -10, max: 10, ...over.rotate },
    scale: { enabled: true, locked: false, min: 0, max: 20 },
    compress: { enabled: true, locked: true, min: 80, max: 90 },
    brightness: { enabled: true, locked: true, min: -5, max: 5 },
    contrast: { enabled: false, locked: true, min: -5, max: 5 },
    saturation: { enabled: true, locked: false, min: -5, max: 5 },
    gamma: { enabled: false, locked: true, min: -5, max: 5 },
    hue: { enabled: true, locked: true, min: -20, max: 20 },
  }
}
