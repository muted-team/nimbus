import { beforeEach, expect, it, vi } from "vitest"
vi.mock("@/api/accounts", () => ({
  PURGE_POLL_MS: 1,
  deleteAccount: vi.fn(),
  loadPurgeStatus: vi.fn(),
  loginAccount: vi.fn(),
  purgeAccount: vi.fn(),
  refreshAccounts: vi.fn(),
  refreshAccountsSoon: vi.fn(),
}))
vi.mock("@/api/registration", () => ({
  startRegistration: vi.fn(),
  registrationStatus: vi.fn(),
}))
vi.mock("@/lib/notify", () => ({
  notify: { ok: vi.fn(), warn: vi.fn(), error: vi.fn() },
}))
import { ApiError } from "@/api/client"
import { startRegistration } from "@/api/registration"
import { startRun, useAccountsRun } from "./accounts-run"
beforeEach(() => {
  vi.clearAllMocks()
  useAccountsRun.setState({
    run: null,
    stopping: false,
    registrationResults: [],
    registrationCurrent: null,
  })
})
const params = {
  mode: 4 as const,
  anymessage_token: "SYNTHETIC",
  age_min: 18,
  age_max: 28,
  domains: ["gmail.com", "outlook.com"],
}
it("uses the existing queue serially and saves every distinct account result", async () => {
  let finish!: (value: {
    status: "complete"
    username: string
    account_saved: true
  }) => void
  vi.mocked(startRegistration)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    .mockResolvedValueOnce({
      status: "complete",
      username: "two",
      account_saved: true,
    })
  startRun("register", ["Registration 1", "Registration 2"], 1, {
    registration: params,
  })
  await vi.waitFor(() => expect(startRegistration).toHaveBeenCalledTimes(1))
  finish({ status: "complete", username: "one", account_saved: true })
  await vi.waitFor(() => expect(useAccountsRun.getState().run).toBeNull())
  expect(startRegistration).toHaveBeenCalledTimes(2)
  expect(
    useAccountsRun.getState().registrationResults.map((row) => row.username)
  ).toEqual(["one", "two"])
  expect(startRegistration).toHaveBeenNthCalledWith(1, params)
})
it("stops remaining registrations on unknown without repeating the current job", async () => {
  vi.mocked(startRegistration).mockResolvedValue({
    status: "interrupted_or_unknown",
    reason: "fixture unknown",
  })
  startRun(
    "register",
    ["Registration 1", "Registration 2", "Registration 3"],
    1,
    { registration: params }
  )
  await vi.waitFor(() => expect(useAccountsRun.getState().run).toBeNull())
  expect(startRegistration).toHaveBeenCalledTimes(1)
  expect(useAccountsRun.getState().registrationResults).toHaveLength(1)
})
it("does not continue after unknown billing even when account was saved", async () => {
  vi.mocked(startRegistration).mockResolvedValue({
    status: "complete",
    account_saved: true,
    username: "one",
    billing_status: "unknown",
  })
  startRun("register", ["Registration 1", "Registration 2"], 1, {
    registration: params,
  })
  await vi.waitFor(() => expect(useAccountsRun.getState().run).toBeNull())
  expect(startRegistration).toHaveBeenCalledTimes(1)
})

it("a known empty proxy pool is a failed admission, not an invented account outcome", async () => {
  vi.mocked(startRegistration).mockRejectedValue(
    new ApiError("Нет живых прокси для регистрации", 409)
  )
  startRun("register", ["Registration 1", "Registration 2"], 1, {
    registration: params,
  })
  await vi.waitFor(() => expect(useAccountsRun.getState().run).toBeNull())
  expect(startRegistration).toHaveBeenCalledTimes(1)
  expect(useAccountsRun.getState().registrationResults[0]).toMatchObject({
    status: "failed",
    reason: "Нет живых прокси для регистрации",
  })
})
