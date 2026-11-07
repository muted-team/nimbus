import { afterEach, beforeEach, expect, it, vi } from "vitest"

vi.mock("@/api/accounts", () => ({
  PURGE_POLL_MS: 1,
  deleteAccount: vi.fn(),
  loadPurgeStatus: vi.fn(),
  loginAccount: vi.fn(),
  purgeAccount: vi.fn(),
  refreshAccounts: vi.fn(),
  refreshAccountsSoon: vi.fn(),
}))
vi.mock("@/lib/notify", () => ({
  notify: { ok: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))

import { loadPurgeStatus, loginAccount, purgeAccount } from "@/api/accounts"
import type { LoginResponse } from "@/api/types"
import { notify } from "@/lib/notify"
import { startRun, useAccountsRun } from "./accounts-run"

beforeEach(() => {
  vi.clearAllMocks()
  useAccountsRun.setState({ run: null, stopping: false })
})

afterEach(async () => {
  await vi.waitFor(() => expect(useAccountsRun.getState().run).toBeNull())
})

it("один аккаунт в исходном списке не входит параллельно самому себе", async () => {
  let finish!: (value: LoginResponse) => void
  const pending = new Promise<LoginResponse>((resolve) => { finish = resolve })
  vi.mocked(loginAccount).mockImplementation(() => pending)
  startRun("login", ["fixture-one", "fixture-one"], 4)
  try {
    expect(loginAccount).toHaveBeenCalledTimes(1)
    expect(useAccountsRun.getState().run?.total).toBe(1)
  } finally {
    // Один promise на все вызовы, чтобы завершить и старую реализацию.
    useAccountsRun.getState().requestStop()
    finish({ ok: true, username: "fixture-one" })
  }
})

it("повторы в добавляемой пачке не ставят аккаунт в очередь дважды", async () => {
  let finish!: (value: LoginResponse) => void
  const pending = new Promise<LoginResponse>((resolve) => { finish = resolve })
  vi.mocked(loginAccount).mockImplementation((username) =>
    username === "fixture-one" ? pending : Promise.resolve({ ok: true, username }))
  startRun("login", ["fixture-one"], 1)
  startRun("login", ["fixture-two", "fixture-two"], 1)
  try {
    expect(useAccountsRun.getState().run?.total).toBe(2)
  } finally {
    finish({ ok: true, username: "fixture-one" })
  }
  await vi.waitFor(() => expect(useAccountsRun.getState().run).toBeNull())
  expect(vi.mocked(loginAccount).mock.calls.map(([username]) => username)).toEqual([
    "fixture-one", "fixture-two",
  ])
})

it("исчезнувшая без результата чистка не считается успешной", async () => {
  vi.mocked(purgeAccount).mockResolvedValue({ ok: true })
  vi.mocked(loadPurgeStatus).mockResolvedValue({ current: [], results: {} })
  startRun("purge", ["fixture-one"])
  await vi.waitFor(() => expect(useAccountsRun.getState().run).toBeNull())
  expect(notify.ok).not.toHaveBeenCalled()
  expect(notify.error).toHaveBeenCalledWith(expect.any(String), undefined, {
    lines: [expect.stringContaining("результат очистки не получен")],
  })
})
