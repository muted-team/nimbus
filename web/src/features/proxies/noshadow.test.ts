import { describe, expect, it } from "vitest"

import {
  generateNoshadow,
  noshadowAccounts,
  patchNoshadow,
  readNoshadow,
  readNoshadowAccount,
  writeNoshadow,
} from "./noshadow"

const SOCKS = "socks5://acc-country-US-session-ab12-time-15:p%40ss@proxy.noshadow.pro:9696"

describe("readNoshadow", () => {
  it("разбирает суффиксы логина и порт", () => {
    expect(readNoshadow(SOCKS)).toEqual({
      base: "acc",
      password: "p@ss",
      country: "US",
      session: "ab12",
      minutes: 15,
      transport: "socks",
      rotateUrl: "",
    })
  })

  it("суффиксы в любом порядке, без них — ротация", () => {
    expect(readNoshadow("http://acc-time-10-country-de:pw@proxy.noshadow.pro:6969")).toMatchObject({
      country: "DE",
      minutes: 10,
      transport: "http",
    })
    expect(readNoshadow("http://acc:pw@proxy.noshadow.pro:6969")).toMatchObject({
      base: "acc",
      country: "",
      minutes: 0,
    })
  })

  it("чужой хост и незнакомый хвост логина — не noshadow", () => {
    expect(readNoshadow("http://acc-country-US:pw@other.host:6969")).toBeNull()
    expect(readNoshadow("http://acc-country-US-rotate-1:pw@proxy.noshadow.pro:6969")).toBeNull()
    expect(readNoshadow("http://acc-time-500:pw@proxy.noshadow.pro:6969")).toBeNull()
    expect(readNoshadow("http://acc-time-abc:pw@proxy.noshadow.pro:6969")).toBeNull()
    expect(readNoshadow("http://proxy.noshadow.pro:6969")).toBeNull()
  })
})

describe("writeNoshadow", () => {
  it("собирает строку обратно", () => {
    const n = readNoshadow(SOCKS)!
    expect(writeNoshadow(n)).toBe("socks5://acc-country-US-session-ab12-time-15:p@ss@proxy.noshadow.pro:9696")
    expect(writeNoshadow({ ...n, transport: "http", minutes: 0 })).toBe(
      "http://acc-country-US-session-ab12:p@ss@proxy.noshadow.pro:6969"
    )
  })
})

describe("patchNoshadow", () => {
  it("липкому IP заводит сессию, ротация её оставляет", () => {
    const bare = readNoshadow("http://acc-country-US:pw@proxy.noshadow.pro:6969")!
    const sticky = patchNoshadow(bare, { minutes: 20 })
    expect(sticky.minutes).toBe(20)
    expect(sticky.session).toMatch(/^[0-9a-f]{8}$/)
    const rotating = patchNoshadow(sticky, { minutes: 0 })
    expect(rotating.minutes).toBe(0)
    expect(rotating.session).toBe(sticky.session)
  })

  it("renew меняет только сессию", () => {
    const n = readNoshadow(SOCKS)!
    const renewed = patchNoshadow(n, { renew: true })
    expect(renewed.session).not.toBe(n.session)
    expect({ ...renewed, session: n.session }).toEqual(n)
  })

  it("не заданное в правке остаётся как было", () => {
    const n = readNoshadow(SOCKS)!
    expect(patchNoshadow(n, { country: "GB" })).toEqual({ ...n, country: "GB" })
  })
})

describe("generateNoshadow", () => {
  it("на каждую страну perCountry разных строк", () => {
    const lines = generateNoshadow({
      base: "acc",
      password: "pw",
      countries: ["US", "DE"],
      perCountry: 3,
      minutes: 15,
      transport: "http",
    })
    expect(lines).toHaveLength(6)
    expect(new Set(lines).size).toBe(6)
    expect(lines.filter((l) => l.includes("-country-DE-")).length).toBe(3)
    expect(lines.every((l) => l.endsWith("@proxy.noshadow.pro:6969"))).toBe(true)
  })
})

describe("readNoshadowAccount", () => {
  it("логин:пароль или целая строка, суффиксы отбрасываются", () => {
    expect(readNoshadowAccount("acc:pw")).toEqual({ base: "acc", password: "pw" })
    expect(readNoshadowAccount(" acc-country-US-time-5:pw ")).toEqual({ base: "acc", password: "pw" })
    expect(readNoshadowAccount(SOCKS)).toEqual({ base: "acc", password: "p@ss" })
    expect(readNoshadowAccount("1.2.3.4:8080:u:p")).toBeNull()
    expect(readNoshadowAccount("")).toBeNull()
  })
})

describe("noshadowAccounts", () => {
  it("учётки без повторов, прочие строки мимо", () => {
    expect(
      noshadowAccounts([
        SOCKS,
        "http://acc-country-DE:p%40ss@proxy.noshadow.pro:6969",
        "http://other:pw@1.2.3.4:8080",
      ])
    ).toEqual([{ base: "acc", password: "p@ss" }])
  })
})
