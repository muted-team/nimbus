import { spawnSync } from "node:child_process"
import { createElement, Fragment, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"
import type { BarAction } from "@/components/selection-bar"
import type { ProxiesResponse } from "@/api/types"
import type { ProxyRowActions } from "./proxy-row"

const fixture = vi.hoisted(() => ({
  actions: [] as BarAction[], busy: new Set<number>(), menu: null as ProxyRowActions["menu"] | null,
  rowActions: null as ProxyRowActions | null,
  data: {
    enabled: true, rotating: 2, errors: [],
    proxies: ["http://one.invalid:8080", "http://two.invalid:8080", "http://hidden.invalid:8080"],
    health: [
      { proxy: "one.invalid:8080", state: "ok", rotating: true },
      { proxy: "two.invalid:8080", state: "ok", rotating: true },
      { proxy: "hidden.invalid:8080", state: "dead", registration: true },
    ],
  } as ProxiesResponse,
}))

// SSR has no interaction lifecycle; inject selection and observe the real page handlers.
vi.mock("react", async (original) => {
  const react = await original<typeof import("react")>()
  return {
    ...react,
    useState: (initial: unknown) => {
      const [value, set] = react.useState(initial)
      if (value instanceof Set) return [value, (update: Set<number> | ((busy: Set<number>) => Set<number>)) => {
        fixture.busy = typeof update === "function" ? update(fixture.busy) : update
      }]
      if (value && typeof value === "object" && "selected" in value)
        return [{ ...value, selected: new Set([0, 1]) }, set]
      return [value, set]
    },
  }
})
vi.mock("@/api/proxies", () => ({
  useProxies: () => ({ data: fixture.data, dataUpdatedAt: Date.now() }),
  saveProxies: vi.fn(async (patch) => patch),
  rotateProxy: vi.fn(),
}))
vi.mock("@/components/page", () => ({
  Page: ({ children }: PropsWithChildren) => createElement(Fragment, null, children),
  PageBody: ({ children }: PropsWithChildren) => createElement(Fragment, null, children),
  PageHeader: () => null,
}))
vi.mock("@/components/selection-bar", () => ({
  SelectionBar: ({ actions }: { actions: BarAction[] }) => { fixture.actions = actions; return null },
}))
vi.mock("./proxies-table", () => ({ ProxiesTable: ({ actions }: { actions: ProxyRowActions }) => {
  fixture.menu = actions.menu
  fixture.rowActions = actions
  return null
} }))
vi.mock("./proxy-capacity", () => ({ ProxyCapacity: () => null }))
vi.mock("@/hooks/use-hotkey", () => ({ useHotkey: vi.fn() }))
vi.mock("@/hooks/use-now", () => ({ useNow: () => Date.now() }))
vi.mock("@/components/confirm", () => ({ confirmDestructive: vi.fn(async () => true) }))
vi.mock("@/lib/notify", () => ({ notify: { ok: vi.fn(), warn: vi.fn(), error: vi.fn() } }))

import { rotateProxy, saveProxies } from "@/api/proxies"
import { notify } from "@/lib/notify"
import { confirmDestructive } from "@/components/confirm"
import { toProxyRows } from "./filter"
import { PROXIES_TOAST } from "./labels"
import { useProxiesStore } from "./proxies-store"
import { keys, queryClient } from "@/api/query-client"
import ProxiesPage from "./proxies-page"

beforeEach(() => {
  vi.clearAllMocks()
  useProxiesStore.setState({ mutating: false })
  queryClient.clear()
  fixture.busy = new Set()
  fixture.data = {
    enabled: true, rotating: 2, errors: [],
    proxies: ["http://one.invalid:8080", "http://two.invalid:8080", "http://hidden.invalid:8080"],
    health: [
      { proxy: "one.invalid:8080", state: "ok", rotating: true },
      { proxy: "two.invalid:8080", state: "ok", rotating: true },
      { proxy: "hidden.invalid:8080", state: "dead", registration: true },
    ],
  }
  renderToStaticMarkup(createElement(ProxiesPage))
})

it("reserves every queued selected proxy until its rotation finishes", async () => {
  let firstDone!: () => void
  let secondDone!: () => void
  vi.mocked(rotateProxy)
    .mockImplementationOnce(() => new Promise((resolve) => { firstDone = () => resolve({ ok: true, ip_before: null, ip_after: null, reason: null }) }))
    .mockImplementationOnce(() => new Promise((resolve) => { secondDone = () => resolve({ ok: true, ip_before: null, ip_after: null, reason: null }) }))
  fixture.actions.find((a) => a.key === "rotate")!.onClick()
  expect(fixture.busy).toEqual(new Set([0, 1]))
  expect(rotateProxy).toHaveBeenCalledExactlyOnceWith(0)
  firstDone()
  await vi.waitFor(() => expect(rotateProxy).toHaveBeenCalledTimes(2))
  expect(fixture.busy).toEqual(new Set([1]))
  expect(rotateProxy).toHaveBeenLastCalledWith(1)
  secondDone()
  await vi.waitFor(() => expect(fixture.busy.size).toBe(0))
})

it("preserves hidden registration assignments when removing selected rows", async () => {
  fixture.actions.find((a) => a.key === "remove")!.onClick()
  await vi.waitFor(() => expect(saveProxies).toHaveBeenCalledWith({
    text: "http://hidden.invalid:8080", login: [], publish: [], registration: [0], off: [],
  }))
})

it("assigns registration without dropping existing marks outside the selection", async () => {
  fixture.actions.find((a) => a.key === "registration-on")!.onClick()
  await vi.waitFor(() => expect(saveProxies).toHaveBeenCalledWith({ registration: [2, 0, 1] }))
})

it("removes only the selected registration marks", async () => {
  fixture.actions.find((a) => a.key === "registration-off")!.onClick()
  await vi.waitFor(() => expect(saveProxies).toHaveBeenCalledWith({ registration: [2] }))
})

it("keeps the specific registration assignment error instead of a generic toggle error", async () => {
  const error = new Error("synthetic save denied")
  vi.mocked(saveProxies).mockRejectedValueOnce(error)
  fixture.actions.find((a) => a.key === "registration-on")!.onClick()
  await vi.waitFor(() => expect(notify.error).toHaveBeenCalledWith(error, PROXIES_TOAST.notRegistration))
})

it("blocks B/C rotation throughout deferred A deletion so shifted index 2 never rotates D", async () => {
  const proxies = ["a", "b", "c", "d"].map((name) => `http://${name}.invalid:8080`)
  fixture.data = { enabled: true, rotating: 4, errors: [], proxies,
    health: proxies.map((proxy) => ({ proxy, state: "ok", rotating: true })) }
  renderToStaticMarkup(createElement(ProxiesPage))
  const rows = toProxyRows(fixture.data.health, proxies)
  const removeA = fixture.menu!([rows[0]]).find((a) => a.key === "remove")!
  const rotateBC = fixture.menu!([rows[1], rows[2]]).find((a) => a.key === "rotate")!
  let confirm!: (ok: boolean) => void
  let finishPut!: () => void
  let persisted = [...proxies]
  const rotated: string[] = []
  vi.mocked(confirmDestructive).mockImplementationOnce(() => new Promise((resolve) => { confirm = resolve }))
  vi.mocked(saveProxies).mockImplementationOnce(async (patch) => {
    await new Promise<void>((resolve) => { finishPut = resolve })
    persisted = patch.text!.split("\n")
    return { ...fixture.data, proxies: persisted }
  })
  vi.mocked(rotateProxy).mockImplementation(async (index) => {
    rotated.push(persisted[index])
    return { ok: true, ip_before: null, ip_after: null, reason: null }
  })
  removeA.onClick()
  rotateBC.onClick()
  await Promise.resolve()
  expect(rotateProxy).not.toHaveBeenCalled()
  expect(saveProxies).not.toHaveBeenCalled()
  confirm(true)
  await vi.waitFor(() => expect(saveProxies).toHaveBeenCalledTimes(1))
  rotateBC.onClick()
  await Promise.resolve()
  expect(rotateProxy).not.toHaveBeenCalled()
  finishPut()
  await vi.waitFor(() => expect(persisted).toEqual(proxies.slice(1)))
  expect(rotated).not.toContain(proxies[3])
  fixture.data = { ...fixture.data, proxies: persisted,
    health: persisted.map((proxy) => ({ proxy, state: "ok", rotating: true })) }
  renderToStaticMarkup(createElement(ProxiesPage))
  fixture.menu!(toProxyRows(fixture.data.health, persisted).slice(0, 2)).find((a) => a.key === "rotate")!.onClick()
  await vi.waitFor(() => expect(rotated).toEqual(proxies.slice(1, 3)))
})

it("rejects deletion from an old menu while B/C rotation is already queued", async () => {
  const rows = toProxyRows(fixture.data.health, fixture.data.proxies)
  const removeHidden = fixture.menu!([rows[2]]).find((a) => a.key === "remove")!
  const rotate = fixture.actions.find((a) => a.key === "rotate")!
  let finish!: () => void
  vi.mocked(rotateProxy).mockImplementationOnce(() => new Promise((resolve) => {
    finish = () => resolve({ ok: true, ip_before: null, ip_after: null, reason: null })
  })).mockResolvedValue({ ok: true, ip_before: null, ip_after: null, reason: null })
  rotate.onClick()
  removeHidden.onClick()
  expect(confirmDestructive).not.toHaveBeenCalled()
  expect(saveProxies).not.toHaveBeenCalled()
  finish()
  await vi.waitFor(() => expect(fixture.busy.size).toBe(0))
})

it.each(["cancel", "failure"])("releases the synchronous deletion guard after %s", async (outcome) => {
  const remove = fixture.actions.find((a) => a.key === "remove")!
  const rotate = fixture.actions.find((a) => a.key === "rotate")!
  if (outcome === "cancel") vi.mocked(confirmDestructive).mockResolvedValueOnce(false)
  else vi.mocked(saveProxies).mockRejectedValueOnce(new Error("synthetic deletion denied"))
  vi.mocked(rotateProxy).mockResolvedValue({ ok: true, ip_before: null, ip_after: null, reason: null })
  remove.onClick()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  if (outcome === "failure") await vi.waitFor(() => expect(notify.error).toHaveBeenCalled())
  rotate.onClick()
  await vi.waitFor(() => expect(rotateProxy).toHaveBeenCalledTimes(2))
})

it("warns instead of confirming renewal when the deferred save reports a rejected line", async () => {
  const proxy = "http://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:6969"
  fixture.data = { enabled: true, rotating: 0, errors: [], proxies: [proxy],
    health: [{ proxy: "proxy.noshadow.pro:6969", state: "ok" }] }
  renderToStaticMarkup(createElement(ProxiesPage))
  let finish!: () => void
  vi.mocked(saveProxies).mockImplementationOnce(() => new Promise((resolve) => {
    finish = () => resolve({ ...fixture.data, errors: [{ line: 1, error: "synthetic renewal refused" }] })
  }))
  fixture.menu!(toProxyRows(fixture.data.health, fixture.data.proxies)).find((a) => a.key === "renew")!.onClick()
  expect(saveProxies).toHaveBeenCalledTimes(1)
  expect(notify.ok).not.toHaveBeenCalled()
  finish()
  await vi.waitFor(() => expect(notify.warn).toHaveBeenCalledWith("Synthetic renewal refused."))
  expect(notify.ok).not.toHaveBeenCalled()
})

it("does not resubmit an unselected malformed row that the backend would drop during renewal", () => {
  const proxy = "http://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:6969"
  const malformed = "http://other.invalid:not-a-port"
  fixture.data = { enabled: true, rotating: 0, errors: [], proxies: [proxy, malformed],
    health: [{ proxy: "proxy.noshadow.pro:6969", state: "ok" }, { proxy: "other.invalid", state: "unknown", registration: true }] }
  renderToStaticMarkup(createElement(ProxiesPage))
  fixture.menu!(toProxyRows(fixture.data.health, fixture.data.proxies).slice(0, 1)).find((a) => a.key === "renew")!.onClick()
  expect(saveProxies).not.toHaveBeenCalled()
  expect(fixture.data.proxies).toEqual([proxy, malformed])
  expect(notify.warn).toHaveBeenCalledWith(PROXIES_TOAST.notChanged)
  expect(notify.ok).not.toHaveBeenCalled()
})

it("warns about partial renewal against the real backend parser", async () => {
  const { spawnSync } = await import("node:child_process")
  const proxy = "http://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:6969"
  const rejected = "http://other.invalid:0"
  fixture.data = { enabled: true, rotating: 0, errors: [], proxies: [proxy, rejected],
    health: [{ proxy: "proxy.noshadow.pro:6969", state: "ok" }, { proxy: "other.invalid", state: "unknown", registration: true }] }
  renderToStaticMarkup(createElement(ProxiesPage))
  vi.mocked(saveProxies).mockImplementationOnce(async (body) => {
    const python = spawnSync(process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"), ["-c", String.raw`
import json, socket, sys, tempfile
from pathlib import Path
from unittest.mock import patch
import main
from modules import config, paths, proxy_pool
body = json.load(sys.stdin)
with tempfile.TemporaryDirectory(dir="web/src/features/proxies") as directory:
    with paths.use_root(Path(directory).resolve()), patch.object(proxy_pool, "snapshot", return_value=[]), patch.object(proxy_pool, "prune"), patch.object(socket.socket, "connect", side_effect=AssertionError("external requests forbidden")):
        config.save({"proxies": [], "proxy_enabled": True})
        handler = main.Handler.__new__(main.Handler)
        handler._read_json = lambda: (body, None)
        handler._campaign_running = lambda: False
        replies = []
        handler._json = lambda value, *args: replies.append(value)
        handler._api_proxies_put()
        print(json.dumps(replies[0]))
`], { cwd: new URL("../../../../", import.meta.url), env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", NIMBUS_DATA_ROOT: "" },
      input: JSON.stringify(body), encoding: "utf8" })
    expect(python.status, python.stderr).toBe(0)
    const response: ProxiesResponse = JSON.parse(python.stdout)
    expect(response.proxies).toHaveLength(1)
    expect(response.errors).toHaveLength(1)
    return response
  })
  fixture.menu!(toProxyRows(fixture.data.health, fixture.data.proxies).slice(0, 1)).find((a) => a.key === "renew")!.onClick()
  await vi.waitFor(() => expect(notify.warn).toHaveBeenCalledTimes(1))
  expect(notify.ok).not.toHaveBeenCalled()
})

// Real PUT/index mapping with isolated synthetic config; no application server or network.
function applyProxyPut(body: unknown, config: Record<string, unknown>) {
  const python = spawnSync(process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"), ["-c", String.raw`
import json, socket, sys, tempfile
from pathlib import Path
from unittest.mock import patch
import main
from modules import config, paths, proxy_pool
payload = json.load(sys.stdin)
with tempfile.TemporaryDirectory(dir="web/src/features/proxies") as directory:
    with paths.use_root(Path(directory).resolve()), patch.object(proxy_pool, "_ensure_auto_check"), patch.object(proxy_pool, "_pulse"), patch.object(socket.socket, "connect", side_effect=AssertionError("external requests forbidden")):
        config.save(payload["config"])
        handler = main.Handler.__new__(main.Handler)
        handler._read_json = lambda: (payload["body"], None)
        handler._campaign_running = lambda: False
        replies = []
        handler._json = lambda value, *args: replies.append(value)
        handler._api_proxies_put()
        print(json.dumps({"response": replies[0], "config": config.load()}))
`], { cwd: new URL("../../../../", import.meta.url), env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", NIMBUS_DATA_ROOT: "" },
    input: JSON.stringify({ body, config }), encoding: "utf8", timeout: 10000 })
  expect(python.status, python.stderr).toBe(0)
  return JSON.parse(python.stdout) as { response: ProxiesResponse; config: Record<string, unknown> }
}

it.each(["renew", "checkbox mark"])("refuses %s during deferred deletion, then applies it to the current B/C rather than A/D", async (action) => {
  const proxies = [
    "http://a.invalid:8080",
    "http://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:6969",
    "http://c.invalid:8080", "http://d.invalid:8080",
  ]
  let persisted = { proxies, proxy_enabled: true, proxies_login: [proxies[1]],
    proxies_publish: [proxies[2]], proxies_registration: [], proxies_off: [] } as Record<string, unknown>
  fixture.data = applyProxyPut({ enabled: true }, persisted).response
  queryClient.setQueryData(keys.proxies, fixture.data)
  renderToStaticMarkup(createElement(ProxiesPage))
  const rows = toProxyRows(fixture.data.health, fixture.data.proxies)
  const removeA = fixture.menu!([rows[0]]).find((a) => a.key === "remove")!
  const renewB = fixture.menu!([rows[1]]).find((a) => a.key === "renew")!
  const oldCheckbox = fixture.rowActions!.toggleRegistration
  const pending: { done: boolean; finish: () => void }[] = []
  vi.mocked(saveProxies).mockImplementation((body) => new Promise((resolve) => {
    const request = { done: false, finish: () => {
      if (request.done) return
      request.done = true
      const applied = applyProxyPut(body, persisted)
      persisted = applied.config
      fixture.data = applied.response
      queryClient.setQueryData(keys.proxies, fixture.data)
      resolve(applied.response)
    } }
    pending.push(request)
  }))
  try {
    removeA.onClick()
    await vi.waitFor(() => expect(saveProxies).toHaveBeenCalledTimes(1))
    if (action === "renew") renewB.onClick()
    else oldCheckbox(2, true)
    pending[0].finish()
    await Promise.resolve()
    await Promise.resolve()
    for (const request of pending.slice(1)) request.finish()
    await Promise.resolve()
    await Promise.resolve()
    expect(persisted.proxies).toEqual(proxies.slice(1))
    expect(persisted.proxies_registration).toEqual([])
    expect(saveProxies).toHaveBeenCalledTimes(1)
    await vi.waitFor(() => expect(notify.ok).toHaveBeenCalledExactlyOnceWith(PROXIES_TOAST.deletedMany(1)))
    if (action === "renew") renewB.onClick()
    else oldCheckbox(2, true)
    expect(saveProxies).toHaveBeenCalledTimes(1)

    renderToStaticMarkup(createElement(ProxiesPage))
    if (action === "renew") {
      fixture.menu!(toProxyRows(fixture.data.health, fixture.data.proxies).slice(0, 1)).find((a) => a.key === "renew")!.onClick()
    } else fixture.rowActions!.toggleRegistration(1, true)
    expect(saveProxies).toHaveBeenCalledTimes(2)
    pending[1].finish()
    await Promise.resolve()
    await Promise.resolve()
    if (action === "renew") {
      const saved = persisted.proxies as string[]
      expect(saved).toHaveLength(3)
      expect(saved[0]).not.toContain("session-ab12")
      expect(saved[0]).toContain("country-US")
      expect(saved.slice(1)).toEqual(proxies.slice(2))
      expect(saved).not.toContain(proxies[0])
      await vi.waitFor(() => expect(notify.ok).toHaveBeenCalledTimes(2))
    } else {
      expect(persisted.proxies_registration).toEqual([proxies[2]])
      expect(persisted.proxies_registration).not.toContain(proxies[3])
      expect(notify.ok).toHaveBeenCalledTimes(1)
    }
  } finally {
    for (const request of pending) request.finish()
    await Promise.resolve()
    await Promise.resolve()
  }
}, 30000)

it.each(["renew", "checkbox mark"])("holds the same interlock when %s starts before deletion", async (action) => {
  const proxies = ["http://a.invalid:8080", "http://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:6969", "http://c.invalid:8080"]
  fixture.data = { enabled: true, rotating: 0, errors: [], proxies,
    health: proxies.map((proxy) => ({ proxy, state: "ok" })) }
  renderToStaticMarkup(createElement(ProxiesPage))
  const rows = toProxyRows(fixture.data.health, proxies)
  const removeA = fixture.menu!([rows[0]]).find((a) => a.key === "remove")!
  let finish!: () => void
  vi.mocked(saveProxies).mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve(fixture.data) }))
  if (action === "renew") fixture.menu!([rows[1]]).find((a) => a.key === "renew")!.onClick()
  else fixture.rowActions!.toggleRegistration(2, true)
  removeA.onClick()
  expect(saveProxies).toHaveBeenCalledTimes(1)
  expect(confirmDestructive).not.toHaveBeenCalled()
  finish()
  await vi.waitFor(() => expect(useProxiesStore.getState().mutating).toBe(false))
  removeA.onClick()
  await vi.waitFor(() => expect(saveProxies).toHaveBeenCalledTimes(2))
})

it("rechecks the captured list after deferred deletion confirmation", async () => {
  queryClient.setQueryData(keys.proxies, fixture.data)
  let confirm!: (ok: boolean) => void
  vi.mocked(confirmDestructive).mockImplementationOnce(() => new Promise((resolve) => { confirm = resolve }))
  fixture.actions.find((a) => a.key === "remove")!.onClick()
  const newer = { ...fixture.data, proxies: fixture.data.proxies.slice(1), health: fixture.data.health.slice(1) }
  queryClient.setQueryData(keys.proxies, newer)
  confirm(true)
  await vi.waitFor(() => expect(useProxiesStore.getState().mutating).toBe(false))
  expect(saveProxies).not.toHaveBeenCalled()
  expect(notify.ok).not.toHaveBeenCalled()
})

it("refuses every role and enable/disable writer during another pending mutation", async () => {
  let finish!: () => void
  vi.mocked(saveProxies).mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve(fixture.data) }))
  fixture.actions.find((a) => a.key === "disable")!.onClick()
  for (const action of fixture.actions.filter((a) => /(?:login|publish|registration)-(?:on|off)$/.test(a.key))) action.onClick()
  fixture.rowActions!.toggleLogin(1, true)
  fixture.rowActions!.togglePublish(1, true)
  fixture.rowActions!.toggleRegistration(1, true)
  fixture.menu!(toProxyRows(fixture.data.health, fixture.data.proxies).map((r) => ({ ...r, enabled: false }))).find((a) => a.key === "enable")!.onClick()
  expect(saveProxies).toHaveBeenCalledTimes(1)
  expect(notify.ok).not.toHaveBeenCalled()
  finish()
  await vi.waitFor(() => expect(useProxiesStore.getState().mutating).toBe(false))
  expect(notify.ok).toHaveBeenCalledTimes(1)
})
