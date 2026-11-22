import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { ColumnKey } from "./columns"

const saved = new Map<string, string>()

beforeEach(() => {
  saved.clear()
  vi.resetModules()
  const localStorage = { getItem: (key: string) => saved.get(key) ?? null, setItem: (key: string, value: string) => saved.set(key, value) }
  vi.stubGlobal("localStorage", localStorage)
  vi.stubGlobal("window", {
    localStorage,
    addEventListener: vi.fn(),
  })
})

afterEach(() => vi.unstubAllGlobals())

describe("persisted account columns", () => {
  it("defaults retain existing metrics and avatar/handle while extra fields start hidden", async () => {
    const { useAccountsView } = await import("./accounts-view")
    expect(useAccountsView.getState().hidden).toEqual(expect.arrayContaining([
      "nickname", "login", "user_id", "following", "verified", "private",
    ]))
    for (const key of ["avatar", "name", "region", "followers", "likes", "views", "posts", "shadow", "fetched"])
      expect(useAccountsView.getState().hidden).not.toContain(key)
  })

  it("individual avatar, handle and name choices survive reloading the store", async () => {
    const { useAccountsView } = await import("./accounts-view")
    for (const key of ["avatar", "name", "nickname"] as ColumnKey[]) useAccountsView.getState().toggleColumn(key)
    const hidden = useAccountsView.getState().hidden
    expect(hidden).toContain("avatar")
    expect(hidden).toContain("name")
    expect(hidden).not.toContain("nickname")
    vi.resetModules()
    const reloaded = await import("./accounts-view")
    expect(reloaded.useAccountsView.getState().hidden).toEqual(hidden)
  })

  it("legacy hidden metrics and sort settings survive adding new optional columns", async () => {
    saved.set("accounts.view", JSON.stringify({ filter: "all", sort: "followers", dir: "desc", hidden: ["region", "likes"] }))
    const { useAccountsView } = await import("./accounts-view")
    expect(useAccountsView.getState()).toMatchObject({ filter: "all", sort: "followers", dir: "desc" })
    expect(useAccountsView.getState().hidden).toEqual(expect.arrayContaining(["region", "likes", "nickname", "user_id"]))
  })
})
