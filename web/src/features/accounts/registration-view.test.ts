import { describe, expect, it } from "vitest"
import {
  modeAvailable,
  registrationBusy,
  registrationPolling,
} from "./registration-view"

describe("registration acceptance", () => {
  it("never offers missing or unavailable server modes", () => {
    expect(modeAvailable(null, 4)).toBe(false)
    expect(
      modeAvailable(
        { modes: [{ mode: 4, supported: true, available: false }] },
        4
      )
    ).toBe(false)
    expect(
      modeAvailable(
        { modes: [{ mode: 3, supported: true, available: true }] },
        4
      )
    ).toBe(false)
  })
  it("unknown dispatch blocks another creation and never triggers automatic polling retries", () => {
    expect(registrationBusy({ status: "dispatch_unknown" })).toBe(true)
    expect(registrationPolling({ status: "dispatch_unknown" })).toBe(false)
    expect(registrationBusy({ status: "interrupted_or_unknown" })).toBe(true)
  })
  it("polls a queued job and permits explicit new registration after confirmed completion", () => {
    expect(registrationPolling({ status: "queued" })).toBe(true)
    expect(registrationPolling({ status: "running" })).toBe(true)
    expect(registrationBusy({ status: "complete", account_saved: true })).toBe(
      false
    )
  })
})
