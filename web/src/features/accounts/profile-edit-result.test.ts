import { describe, expect, it } from "vitest"
import {
  profileOutcome,
  profileNeedsReadback,
  usernameStepText,
} from "./profile-edit-result"
const before = { user_id: "123", nickname: "Old", unique_id: "old_name" }
const success = {
  verdict: "confirmed",
  before,
  after: { ...before, unique_id: "new_name" },
  confirmed_fields: ["unique_id"],
  platform_verified: true,
}
describe("profile readback acceptance", () => {
  it("requires confirmed field, exact UID and actual username", () => {
    expect(profileOutcome(success, { unique_id: "new_name" }, "123")).toBe(
      "confirmed"
    )
    expect(
      profileOutcome(
        { ...success, confirmed_fields: [] },
        { unique_id: "new_name" },
        "123"
      )
    ).toBe("unknown")
    expect(
      profileOutcome(
        { ...success, after: { ...before, user_id: "999" } },
        { unique_id: "new_name" },
        "123"
      )
    ).toBe("unknown")
    expect(
      profileOutcome(
        { ...success, after: before },
        { unique_id: "new_name" },
        "123"
      )
    ).toBe("unknown")
  })
  it("available alone and unknown/blocked never become success", () => {
    expect(
      profileOutcome({ verdict: "available" }, { unique_id: "new_name" }, "123")
    ).toBe("unknown")
    expect(profileOutcome({ verdict: "blocked" }, {}, "123")).toBe("blocked")
    expect(
      profileOutcome(
        {
          verdict: "partial",
          before,
          after: { ...before, nickname: "Весна 🌷" },
          confirmed_fields: ["nickname"],
        },
        { nickname: "Весна 🌷", unique_id: "new_name" },
        "123"
      )
    ).toBe("partial")
  })
  it("unknown username substep and unsaved state require fresh readback", () => {
    expect(
      profileNeedsReadback({
        verdict: "partial",
        steps: [{ step: "username_update", verdict: "unknown" }],
      })
    ).toBe(true)
    expect(profileNeedsReadback({ ...success, state_saved: false })).toBe(true)
  })
  it("blocks replay when client readback validation rejects server confirmation", () => {
    const response = { ...success, after: { ...before, user_id: "999" } }
    const outcome = profileOutcome(response, { unique_id: "new_name" }, "123")
    expect(outcome).toBe("unknown")
    expect(profileNeedsReadback(response, outcome)).toBe(true)
    expect(profileNeedsReadback(success, "confirmed")).toBe(false)
  })
  it("keeps unavailability and challenges distinct", () => {
    expect(
      usernameStepText({
        step: "username_update",
        verdict: "blocked",
        reason: "unavailable",
      })
    ).toContain("недоступно")
    expect(
      usernameStepText({
        step: "username_update",
        verdict: "blocked",
        reason: "challenge",
      })
    ).toContain("проверку")
  })
})
