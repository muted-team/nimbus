import { spawnSync } from "node:child_process"
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
      durationSuffix: true,
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
    expect(writeNoshadow(n)).toBe("socks5://acc-country-US-session-ab12-time-15:p%40ss@proxy.noshadow.pro:9696")
    expect(writeNoshadow({ ...n, transport: "http", minutes: 0 })).toBe(
      "http://acc-country-US-session-ab12-time-0:p%40ss@proxy.noshadow.pro:6969"
    )
  })

  it("reopens the same settings with reserved characters in credentials", () => {
    const n = { ...readNoshadow(SOCKS)!, base: "fixture@name", password: "synthetic@:/#%40" }
    expect(readNoshadow(writeNoshadow(n))).toEqual(n)
  })

  it("escapes apostrophes that the API proxy parser treats as pasted quotation marks", () => {
    const n = { ...readNoshadow(SOCKS)!, password: "synthetic'quote" }
    expect(writeNoshadow(n)).toContain("synthetic%27quote")
  })

  it("does not reset a saved alternate SOCKS port or DNS scheme when changing the country", () => {
    const line = "socks5h://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:1080"
    const changed = writeNoshadow(patchNoshadow(readNoshadow(line)!, { country: "GB" }))
    expect(changed).toBe(line.replace("country-US", "country-GB"))
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

  it("switching transport replaces alternate endpoint fields with the chosen defaults", () => {
    const n = readNoshadow("socks5h://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:1080")!
    expect(writeNoshadow(patchNoshadow(n, { transport: "http" }))).toBe(
      "http://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:6969"
    )
    expect(writeNoshadow(patchNoshadow(n, { renew: true }))).toMatch(/^socks5h:.*:1080$/)
  })

  it("an explicit transport choice applies its default even within the same SOCKS family", () => {
    const n = readNoshadow("socks5h://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:1080")!
    expect(writeNoshadow(patchNoshadow(n, { transport: "socks" }))).toBe(
      "socks5://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:9696"
    )
  })

  it.each([0, 45])("country-only editing preserves explicit time-%i without inserting a session", (minutes) => {
    const line = `http://fixture-country-US-time-${minutes}:synthetic@proxy.noshadow.pro:6969`
    const changed = writeNoshadow(patchNoshadow(readNoshadow(line)!, { country: "GB" }))
    expect(changed).toBe(line.replace("country-US", "country-GB"))
    const python = spawnSync(process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"), ["-c", String.raw`
import json, sys
from modules import proxies
line = json.load(sys.stdin)
print(json.dumps(proxies.noshadow_session(line, "synthetic")))
`], { cwd: new URL("../../../../", import.meta.url), env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", NIMBUS_DATA_ROOT: "" },
      input: JSON.stringify(changed), encoding: "utf8" })
    expect(python.status, python.stderr).toBe(0)
    expect(JSON.parse(python.stdout)).toBe(changed)
  })

  it("records an explicit rotation choice as time-0 without creating a session", () => {
    const line = "http://fixture-country-US:synthetic@proxy.noshadow.pro:6969"
    expect(writeNoshadow(patchNoshadow(readNoshadow(line)!, { minutes: 0 }))).toBe(
      "http://fixture-country-US-time-0:synthetic@proxy.noshadow.pro:6969"
    )
  })

  it("does not insert a session just because an already sticky duration changes", () => {
    const line = "http://fixture-country-US-time-45:synthetic@proxy.noshadow.pro:6969"
    expect(writeNoshadow(patchNoshadow(readNoshadow(line)!, { minutes: 60 }))).toBe(line.replace("time-45", "time-60"))
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
