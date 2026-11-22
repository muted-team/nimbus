import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import type { Account } from "@/api/types"

import { AccountRow } from "./account-row"
import type { RowHandlers } from "./account-row"
import { actionContext } from "./actions"
import { COLUMNS, gridTemplate, visibleColumns } from "./columns"
import type { ColumnKey } from "./columns"

vi.mock("@/components/ui/avatar", async (original) => ({
  ...await original<typeof import("@/components/ui/avatar")>(),
  AvatarImage: ({ src }: { src: string }) => createElement("img", { src, alt: "" }),
}))

const account: Account = {
  username: "fixture@example.invalid", has_session: true, has_totp: false,
  has_email: false, avatar: null, region: null, lang: null,
  profile: { unique_id: "real.profile", nickname: "Весна 🌷" },
}

function render(hidden: ColumnKey[] = [], current = account, avatar?: string) {
  const columns = visibleColumns(3, new Set(hidden))
  return renderToStaticMarkup(createElement(AccountRow, {
    account: current, avatar, busy: false, locked: false, selected: false,
    columns, template: gridTemplate(columns, 3, false),
    handlers: { actions: {} as RowHandlers["actions"], onOpen: vi.fn(), onPick: vi.fn(), onContextSelect: vi.fn() },
    selection: { ctx: actionContext([]), run: vi.fn() },
  }))
}

it("row displays the TikTok handle while selection and actions keep the email alias", () => {
  const html = render()
  expect(html).toContain("@real.profile")
  expect(html).not.toContain("@fixture@example.invalid")
})

describe("independent identity cells", () => {
  it("renders avatar, handle, nickname and original login in separate grid cells", () => {
    const html = render()
    expect(html.match(/role="gridcell"/g)).toHaveLength(COLUMNS.length + 2)
    expect(html).toContain('data-column="avatar"')
    expect(html).toContain('data-column="name"')
    expect(html).toContain('data-column="nickname"')
    expect(html).toContain('data-column="login"')
    expect(html).toContain("Весна 🌷")
    expect(html).toContain("fixture@example.invalid")
  })

  it("hiding one identity cell does not leave it inside another cell", () => {
    expect(render(["avatar"])).not.toContain('data-slot="avatar"')
    expect(render(["nickname"])).not.toContain("Весна 🌷")
    expect(render(["name"])).not.toContain('data-column="name"')
    expect(render(["name"])).toContain("Весна 🌷")
    expect(render(["name"])).toContain('data-slot="avatar"')
  })

  it("a confirmed false profile flag is not displayed as an unknown value", () => {
    const html = render([], { ...account, profile: { verified: false, private_account: false } })
    expect(html).toMatch(/data-column="verified"[^>]*><span>Нет<\/span>/)
    expect(html).toMatch(/data-column="private"[^>]*><span>Нет<\/span>/)
  })

  it("UID conflict is visible beside an unknown handle, not an old cached identity", () => {
    const html = render([], { ...account, profile: { identity_conflict: true } }, "data:image/png;base64,old-fixture-face")
    expect(html).toContain("UID")
    expect(html).not.toContain("@real.profile")
    expect(html).not.toContain("Весна 🌷")
    expect(html).not.toContain("old-fixture-face")
  })
})
