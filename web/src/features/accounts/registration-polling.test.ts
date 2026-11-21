import { afterEach, expect, it, vi } from "vitest"
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
import { startRun, useAccountsRun } from "./accounts-run"
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it("recovers the same admitted job after a real API timeout without another registration POST", async () => {
  vi.useFakeTimers()
  const job = "a".repeat(32)
  let gets = 0
  const fetcher = vi.fn((_path: string, init: RequestInit) => {
    if (init.method === "POST")
      return Promise.resolve(
        new Response(
          JSON.stringify({ status: "queued", job_id: job, scope: "same-scope" })
        )
      )
    gets++
    if (gets === 1)
      return new Promise<Response>((_, reject) =>
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("timeout", "AbortError"))
        )
      )
    return Promise.resolve(
      new Response(
        JSON.stringify({
          status: "complete",
          job_id: job,
          scope: "same-scope",
          account_saved: true,
          username: "confirmed",
        })
      )
    )
  })
  vi.stubGlobal("fetch", fetcher)
  useAccountsRun.setState({
    run: null,
    stopping: false,
    registrationCurrent: null,
    registrationResults: [],
  })
  startRun("register", ["one", "two"], 1, {
    registration: {
      mode: 4,
      anymessage_token: "fixture",
      age_min: 18,
      age_max: 28,
      domains: ["gmail.com"],
    },
  })
  await vi.advanceTimersByTimeAsync(22_100)
  expect(useAccountsRun.getState().registrationPollError).toBeTruthy()
  expect(useAccountsRun.getState().registrationCurrent?.job_id).toBe(job)
  await vi.advanceTimersByTimeAsync(2_100)
  expect(useAccountsRun.getState().run).toBeNull()
  expect(useAccountsRun.getState().registrationCurrent).toMatchObject({
    job_id: job,
    status: "complete",
    account_saved: true,
  })
  expect(useAccountsRun.getState().registrationPollError).toBeNull()
  expect(
    fetcher.mock.calls.filter(([, init]) => init.method === "POST")
  ).toHaveLength(1)
  expect(
    fetcher.mock.calls.filter(
      ([path, init]) => init.method === "GET" && path === "api/registration"
    )
  ).toHaveLength(2)
})
