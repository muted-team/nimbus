import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

import type { Account } from "@/api/types"
import type { AccountRowActions } from "./actions"

vi.mock("@/api/campaign", () => ({ useCampaignStatus: () => ({ data: { results: [] } }) }))
vi.mock("@/api/logs", () => ({ useLogs: (select: (state: { events: [] }) => unknown) => select({ events: [] }) }))
vi.mock("@/components/ui/sheet", () => {
  const block = ({ children }: { children: React.ReactNode }) => createElement("div", null, children)
  return { Sheet: block, SheetContent: block, SheetHeader: block, SheetTitle: block, SheetDescription: block }
})
vi.mock("@/components/ui/avatar", async (original) => ({
  ...await original<typeof import("@/components/ui/avatar")>(),
  AvatarImage: ({ src }: { src: string }) => createElement("img", { src, alt: "" }),
}))

import { AccountSheet } from "./account-sheet"

const account: Account = { username: "fixture@example.invalid", has_session: true,
    has_totp: false, has_email: false, avatar: null, region: null, lang: null,
    profile: { unique_id: "real.profile", nickname: "Весна 🌷" } }

it("account sheet title shows the real TikTok handle and keeps the login separately", () => {
  const html = renderToStaticMarkup(createElement(AccountSheet, {
    account, busy: false, locked: false, actions: {} as AccountRowActions, onClose: vi.fn(),
  }))
  expect(html).toContain("@real.profile")
  expect(html).toContain("fixture@example.invalid")
  expect(html).not.toContain("@fixture@example.invalid")
})

it("a UID-conflict sheet clearly marks the login alias rather than an old TikTok handle", () => {
  const html = renderToStaticMarkup(createElement(AccountSheet, {
    account: { ...account, username: "old.handle", profile: { identity_conflict: true } },
    avatar: "data:image/png;base64,old-fixture-face",
    busy: false, locked: false, actions: {} as AccountRowActions, onClose: vi.fn(),
  }))
  expect(html).toContain("Конфликт UID")
  expect(html).not.toContain("@old.handle")
  expect(html).not.toContain("old-fixture-face")
})
