import { describe, expect, it, vi } from "vitest"
import { registrationIndexes, toProxyRows } from "./filter"
import { indexesAfterRemoval, saveProxiesLines } from "./proxies-store"
import { saveProxies } from "@/api/proxies"

vi.mock("@/api/proxies", () => ({ saveProxies: vi.fn(async (patch) => patch), checkProxies: vi.fn() }))

describe("registration proxy assignments", () => {
  it("keeps existing proxies unassigned unless explicitly marked", () => {
    const rows = toProxyRows([
      { proxy: "same-host:8080", state: "ok", login: true },
      { proxy: "same-host:8080", state: "ok", registration: true },
      { proxy: "other-host:8080", state: "ok", publish: true },
    ])
    expect(registrationIndexes(rows)).toEqual([1])
    expect(registrationIndexes([...rows].reverse())).toEqual([1])
  })

  it("preserves registration marks through full-list edits and index shifts", async () => {
    const registration = indexesAfterRemoval([1, 3], 0)
    await saveProxiesLines(["synthetic-a", "synthetic-b", "synthetic-c"], {
      login: [1], publish: [2], registration, off: [],
    })
    expect(saveProxies).toHaveBeenCalledWith({ text: "synthetic-a\nsynthetic-b\nsynthetic-c",
      login: [1], publish: [2], registration: [0, 2], off: [] })
  })
})
