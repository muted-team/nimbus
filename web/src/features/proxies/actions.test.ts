import { describe, expect, it, vi } from "vitest"
import { CopyIcon, GlobeIcon, LogInIcon, PencilIcon, PowerIcon, PowerOffIcon, RefreshCwIcon, SendIcon, Trash2Icon } from "lucide-react"

import { proxyActions, type ProxyActionKey } from "./actions"
import type { ProxyRow } from "./filter"
import { NOSHADOW_LABEL, PROXIES_LABEL, PROXY_ACTION, PROXY_BULK, rotateWait } from "./labels"

const row = (index: number, patch: Partial<ProxyRow> = {}): ProxyRow => ({
  index, proxy: `fixture-${index}.invalid:8080`, state: "ok", noshadow: null, ...patch,
})
const at = (rows: ProxyRow[], key: ProxyActionKey, flags = {}) => {
  const action = proxyActions(rows, vi.fn(), flags).find((a) => a.key === key)
  expect(action, key).toBeDefined()
  return action!
}

describe("shared proxy menu definitions", () => {
  it("uses the same action names and icon objects for one or several targets", () => {
    const first = row(0, { rotating: true, noshadow: { country: "GB", minutes: 45 } })
    const second = row(1, { enabled: false })
    const one = proxyActions([first], vi.fn())
    const many = proxyActions([first, second], vi.fn())
    for (const single of one.filter((a) => a.key !== "edit")) {
      const group = many.find((a) => a.key === single.key)!
      expect([group.label, group.icon, group.disabled, group.destructive, group.separatorBefore])
        .toEqual([single.label, single.icon, single.disabled, single.destructive, single.separatorBefore])
    }
    expect(one.map((a) => a.key)).toEqual([
      "disable", "copy", "edit", "login-on", "login-off", "registration-on", "registration-off",
      "publish-on", "publish-off", "noshadow", "renew", "rotate", "remove",
    ])
    expect(many.map((a) => a.key)).toEqual([
      "disable", "enable", "copy", "login-on", "login-off", "registration-on", "registration-off",
      "publish-on", "publish-off", "noshadow", "renew", "rotate", "remove",
    ])
  })

  it("reuses existing labels and icons instead of redefining them in each surface", () => {
    const targets = [row(0, { enabled: false, rotating: true, noshadow: { country: "US", minutes: 15 } })]
    const expected = {
      enable: [PROXY_BULK.enable, PowerIcon], copy: [PROXY_BULK.copy, CopyIcon],
      edit: [PROXY_ACTION.edit, PencilIcon], "login-on": [PROXY_BULK.loginOn, LogInIcon],
      "registration-on": [PROXY_BULK.registrationOn, LogInIcon], "publish-on": [PROXY_BULK.publishOn, SendIcon],
      noshadow: [NOSHADOW_LABEL.bulk, GlobeIcon], renew: [NOSHADOW_LABEL.renew, RefreshCwIcon],
      rotate: [PROXIES_LABEL.rotate, RefreshCwIcon], remove: [PROXY_BULK.remove, Trash2Icon],
    }
    for (const [key, values] of Object.entries(expected)) {
      const action = at(targets, key as ProxyActionKey)
      expect([action.label, action.icon]).toEqual(values)
    }
    expect(at([row(0)], "disable").icon).toBe(PowerOffIcon)
  })

  it("keeps NoShadow configuration available on disabled rows, but disables IP changes", () => {
    const targets = [row(0, { enabled: false, rotating: true, noshadow: { country: "GB", minutes: 45 } })]
    expect(at(targets, "noshadow").disabled).toBeFalsy()
    expect(at(targets, "renew").disabled).toBe(true)
    expect(at(targets, "rotate").disabled).toBe(true)
    expect(at(targets, "copy").disabled).toBeFalsy()
    expect(at(targets, "registration-on").disabled).toBeFalsy()
    expect(proxyActions(targets, vi.fn()).map((a) => a.key)).not.toContain("disable")
  })

  it("uses the same cooldown and busy state for row and selection IP actions", () => {
    const targets = [row(4, { rotating: true, rotate_in: 30, noshadow: { country: "GB", minutes: 45 } })]
    expect(at(targets, "rotate", { elapsed: 5 }).label).toBe(rotateWait(25))
    expect(at(targets, "rotate", { elapsed: 5 }).disabled).toBe(true)
    expect(at(targets, "rotate", { elapsed: 30 }).disabled).toBe(false)
    const busy = { elapsed: 30, rotateBusy: new Set([4]) }
    expect(at(targets, "rotate", busy).label).toBe(PROXIES_LABEL.rotating)
    expect(at(targets, "rotate", busy).disabled).toBe(true)
    expect(at(targets, "renew", busy).disabled).toBe(true)
  })

  it("keeps an independent proxy available while another row is rotating", () => {
    const targets = [row(0, { rotating: true })]
    expect(at(targets, "rotate", { rotateBusy: new Set([9]) }).disabled).toBe(false)
  })

  it("prevents index-changing deletion while a selected rotation is queued", () => {
    const targets = [row(0)]
    expect(at(targets, "remove", { rotateBusy: new Set([9]) }).disabled).toBe(true)
    expect(at(targets, "edit", { rotateBusy: new Set([9]) }).disabled).toBeFalsy()
  })

  it("does not rewrite the endpoint of a queued proxy", () => {
    const targets = [row(0, { noshadow: { country: "GB", minutes: 45 } })]
    const flags = { rotateBusy: new Set([0]) }
    expect(at(targets, "edit", flags).disabled).toBe(true)
    expect(at(targets, "noshadow", flags).disabled).toBe(true)
  })

  it("offers bulk rotation when at least one enabled selected proxy can rotate", () => {
    const targets = [row(0, { rotating: true, rotate_in: 30 }), row(1, { rotating: true, enabled: false }), row(2, { rotating: true })]
    expect(at(targets, "rotate").disabled).toBe(false)
    expect(at(targets.slice(0, 2), "rotate").disabled).toBe(true)
    expect(at(targets, "rotate", { rotateBusy: new Set([2]) }).disabled).toBe(true)
  })

  it("omits provider-specific actions where they cannot apply, without losing role assignments", () => {
    const keys = proxyActions([row(0), row(1)], vi.fn()).map((a) => a.key)
    expect(keys).toEqual(["disable", "copy", "login-on", "login-off", "registration-on", "registration-off", "publish-on", "publish-off", "remove"])
    expect(proxyActions([], vi.fn())).toEqual([])
  })

  it("dispatches each action once and separates destructive removal", () => {
    const run = vi.fn()
    const actions = proxyActions([row(0)], run)
    for (const action of actions) action.onClick()
    expect(run.mock.calls.map(([key]) => key)).toEqual(actions.map((a) => a.key))
    expect(actions.filter((a) => a.destructive || a.separatorBefore).map((a) => a.key)).toEqual(["remove"])
  })
})
