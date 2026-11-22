import { describe, expect, it } from "vitest"

import { COLUMNS, gridTemplate, visibleColumns } from "./columns"

describe("available account columns", () => {
  it("keeps existing metrics and offers avatar, handle, display name, login and cached identity separately", () => {
    expect(COLUMNS.map((column) => column.key)).toEqual(expect.arrayContaining([
      "avatar", "name", "nickname", "login", "user_id", "region", "followers", "following",
      "likes", "views", "posts", "shadow", "verified", "private", "fetched",
    ]))
    expect(new Set(COLUMNS.map((column) => column.key)).size).toBe(COLUMNS.length)
  })

  it("avatar, TikTok username and display name can each be hidden without hiding the others", () => {
    for (const key of ["avatar", "name", "nickname"] as const) {
      const visible = visibleColumns(3, new Set([key])).map((column) => column.key)
      expect(visible).not.toContain(key)
      expect(visible).toEqual(expect.arrayContaining(["avatar", "name", "nickname"].filter((other) => other !== key)))
    }
  })

  it("header and rows reserve exactly one grid track per visible column", () => {
    const visible = visibleColumns(3, new Set(["avatar", "nickname"]))
    expect(gridTemplate(visible, 3, false).split(" ")).toHaveLength(visible.length + 2)
  })

  it("explicitly enabled optional fields remain available on narrow screens", () => {
    const hidden = new Set(COLUMNS.filter((c) => c.defaultHidden && c.key !== "nickname").map((c) => c.key))
    expect(visibleColumns(0, hidden).map((c) => c.key)).toEqual(["avatar", "name", "nickname"])
  })
})
