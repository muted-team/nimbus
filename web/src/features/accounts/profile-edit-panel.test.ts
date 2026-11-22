import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

import type { Account } from "@/api/types"

vi.mock("@/components/ui/sheet", () => {
  const block = ({ children }: { children: React.ReactNode }) => createElement("div", null, children)
  return { Sheet: block, SheetContent: block, SheetHeader: block, SheetTitle: block, SheetDescription: block }
})

import { ProfileEditPanel } from "./profile-edit-panel"

it("profile editor initially labels the cached TikTok handle rather than the email session key", () => {
  const account: Account = { username: "fixture@example.invalid", has_session: true,
    has_totp: false, has_email: false, avatar: null, region: null, lang: null,
    profile: { unique_id: "real.profile" } }
  const html = renderToStaticMarkup(createElement(ProfileEditPanel, { account, onClose: vi.fn() }))
  expect(html).toContain("@real.profile")
  expect(html).not.toContain("@fixture@example.invalid")
})
