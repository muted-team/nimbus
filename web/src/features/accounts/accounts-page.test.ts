import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"

import type { Account } from "@/api/types"
import type { AccountRowActions, SelectionActions } from "./actions"
import type { Column } from "./columns"

const fixtures = vi.hoisted(() => ({ accounts: [] as Account[], actions: null as AccountRowActions | null, selection: null as SelectionActions | null, columns: [] as Column[] }))

vi.mock("@/api/accounts", () => ({
  useAccounts: () => ({ data: { accounts: fixtures.accounts, banned: [] } }),
  useAvatars: () => ({ data: {} }), useProfilesRefresh: () => ({ data: { running: false } }),
  usePurgeStatus: () => ({ data: { current: [] } }), startProfilesRefresh: vi.fn().mockResolvedValue({}),
  refreshAccounts: vi.fn(), purgeAccount: vi.fn(), disableAccounts: vi.fn(), restoreAccount: vi.fn(),
}))
vi.mock("@/api/campaign", () => ({ useCampaignStatus: () => ({ data: { status: "idle" } }), isCampaignLive: () => false }))
vi.mock("@/api/misc", () => ({ useSettings: () => ({ data: { threads: 1 } }) }))
vi.mock("@/api/studio", () => ({ useStudioCounters: () => ({ data: {} }) }))
vi.mock("@/features/campaign/launcher", () => ({ useCampaignLauncher: () => ({ launch: vi.fn() }) }))
vi.mock("@/hooks/use-hotkey", () => ({ useHotkey: vi.fn() }))
vi.mock("./accounts-run", () => ({ useAccountsRun: (select: (s: { run: null }) => unknown) => select({ run: null }), startRun: vi.fn() }))
vi.mock("./account-sheet", () => ({ AccountSheet: () => null }))
vi.mock("./add-panel", () => ({ AddPanel: () => null }))
vi.mock("./registration-panel", () => ({ RegistrationPanel: () => null }))
vi.mock("./profile-edit-panel", () => ({ ProfileEditPanel: () => null }))
vi.mock("./edit-panel", () => ({ EditPanel: () => null }))
vi.mock("./accounts-table", () => ({ AccountsTable: (props: { handlers: { actions: AccountRowActions }; columns: Column[] }) => {
  fixtures.actions = props.handlers.actions
  fixtures.columns = props.columns
  return null
} }))
vi.mock("./accounts-bar", () => ({ AccountsBar: (props: { actions: SelectionActions }) => { fixtures.selection = props.actions; return null } }))
vi.mock("./columns", async (original) => ({ ...await original<typeof import("./columns")>(), useTier: () => 3 }))
vi.mock("@/lib/native", async (original) => ({ ...await original<typeof import("@/lib/native")>(), openExternal: vi.fn(), copyWithToast: vi.fn() }))

import { startProfilesRefresh } from "@/api/accounts"
import { copyWithToast, openExternal } from "@/lib/native"
import AccountsPage from "./accounts-page"
import { startRun } from "./accounts-run"
import { useAccountsView } from "./accounts-view"

beforeEach(() => {
  vi.clearAllMocks()
  fixtures.accounts = [{ username: "fixture@example.invalid", has_session: true, has_email: false,
    has_totp: false, avatar: null, region: null, lang: null, profile: { unique_id: "real.profile" } }]
  useAccountsView.setState({ filter: "all", card: null, query: "", selected: new Set([fixtures.accounts[0].username]) })
})

it("open/copy use the real handle, while login and refresh still use the original alias", async () => {
  renderToStaticMarkup(createElement(AccountsPage))
  const alias = fixtures.accounts[0].username
  fixtures.actions!.open(alias)
  fixtures.actions!.copy(alias)
  fixtures.actions!.login(alias)
  fixtures.actions!.refresh(alias)
  fixtures.selection!.copy()
  await Promise.resolve()
  expect(openExternal).toHaveBeenCalledWith("https://www.tiktok.com/@real.profile")
  expect(copyWithToast).toHaveBeenCalledWith("@real.profile", expect.any(String))
  expect(startRun).toHaveBeenCalledWith("login", [alias], 1)
  expect(startProfilesRefresh).toHaveBeenCalledWith([alias])
})

it("initial view keeps the old default metrics rather than enabling all new columns", () => {
  renderToStaticMarkup(createElement(AccountsPage))
  expect(fixtures.columns.map((c) => c.key)).toEqual(["avatar", "name", "region", "followers", "likes", "views", "posts", "shadow", "fetched"])
})

it("an unresolved email never opens a fake TikTok URL or copies the login as a handle", () => {
  fixtures.accounts[0].profile = null
  renderToStaticMarkup(createElement(AccountsPage))
  fixtures.actions!.open(fixtures.accounts[0].username)
  fixtures.actions!.copy(fixtures.accounts[0].username)
  fixtures.selection!.copy()
  expect(openExternal).not.toHaveBeenCalled()
  expect(copyWithToast).not.toHaveBeenCalled()
})
