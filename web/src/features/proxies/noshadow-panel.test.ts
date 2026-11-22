import { createElement, Fragment, type PropsWithChildren, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"

const buttons = vi.hoisted(() => [] as { children?: ReactNode; onClick?: () => void }[])
const editingState = vi.hoisted(() => ({ countries: null as string[] | null }))
vi.mock("react", async (original) => {
  const react = await original<typeof import("react")>()
  return { ...react, useState: (initial: unknown) => {
    const [value, set] = react.useState(initial)
    return [Array.isArray(value) && editingState.countries ? editingState.countries : value, set]
  } }
})
vi.mock("@/components/ui/button", async (original) => {
  const real = await original<typeof import("@/components/ui/button")>()
  return { ...real, Button: (props: Parameters<typeof real.Button>[0]) => {
    buttons.push({ children: props.children, onClick: props.onClick as () => void })
    return createElement(real.Button, props)
  } }
})
vi.mock("./proxies-store", async (original) => ({ ...await original<typeof import("./proxies-store")>(), saveProxiesLines: vi.fn() }))
vi.mock("@/lib/notify", () => ({ notify: { ok: vi.fn(), warn: vi.fn(), error: vi.fn() } }))

// Only remove the portal: render the real form controls and their saved values.
vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({ children }: PropsWithChildren) => createElement(Fragment, null, children),
  SheetContent: ({ children }: PropsWithChildren) => createElement("section", null, children),
  SheetHeader: ({ children }: PropsWithChildren) => createElement("header", null, children),
  SheetTitle: ({ children }: PropsWithChildren) => createElement("h2", null, children),
  SheetFooter: ({ children }: PropsWithChildren) => createElement("footer", null, children),
}))

import { NoshadowPanel } from "./noshadow-panel"
import { NOSHADOW_LABEL as L, PROXIES_TOAST } from "./labels"
import { saveProxiesLines } from "./proxies-store"
import { notify } from "@/lib/notify"

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(saveProxiesLines).mockReset()
  buttons.length = 0
  editingState.countries = null
})

const saved = "socks5://fixture-country-GB-session-ab12-time-45:synthetic@proxy.noshadow.pro:9696"
const marks = { login: [0], publish: [], registration: [0], off: [] }

function reopen(proxies = [saved], editing = [0]) {
  return renderToStaticMarkup(createElement(NoshadowPanel, { proxies, editing, marks, onClose: vi.fn() }))
}

it("reopens a saved NoShadow proxy with its actual country, sticky interval and port", () => {
  for (const html of [reopen(), reopen()]) {
    const active = [...html.matchAll(/<button\b[^>]*aria-pressed="true"[^>]*>([\s\S]*?)<\/button>/g)]
      .map(([, text]) => text)
    expect(active).toEqual([L.sticky, L.socks])
    expect(html).toMatch(/<input\b[^>]*id="ns-minutes"[^>]*value="45"/)
    expect(html).toMatch(/aria-selected="true"[^>]*>[\s\S]*?>GB<\/span>/)
  }
})

it("does not treat displayed saved settings as pending edits", () => {
  const html = reopen()
  const apply = [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)]
    .find(([, , text]) => text === L.apply)
  expect(apply?.[1]).toMatch(/\sdisabled(?:=""|\s|$)/)
})

it("shows the saved settings shared by multiple selected NoShadow proxies", () => {
  const html = reopen([saved, saved.replace("ab12", "cd34")], [0, 1])
  const active = [...html.matchAll(/<button\b[^>]*aria-pressed="true"[^>]*>([\s\S]*?)<\/button>/g)]
    .map(([, text]) => text)
  expect(active).toEqual([L.sticky, L.socks])
  expect(html).toMatch(/<input\b[^>]*id="ns-minutes"[^>]*value="45"/)
})

it("uses Keep only for settings that differ across the selected proxies", () => {
  const other = saved.replace("country-GB", "country-DE").replace("ab12", "cd34").replace("time-45", "time-10")
  const html = reopen([saved, other], [0, 1])
  const active = [...html.matchAll(/<button\b[^>]*aria-pressed="true"[^>]*>([\s\S]*?)<\/button>/g)]
    .map(([, text]) => text)
  expect(active).toEqual([L.keep, L.socks])
  expect(html).not.toContain('aria-selected="true"')
  const apply = [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].find(([, , text]) => text === L.apply)
  expect(apply?.[1]).toMatch(/\sdisabled(?:=""|\s|$)/)
})

it("reopens rotation rather than replacing it with the sticky default", () => {
  const html = reopen([saved.replace("-time-45", "")])
  const active = [...html.matchAll(/<button\b[^>]*aria-pressed="true"[^>]*>([\s\S]*?)<\/button>/g)]
    .map(([, text]) => text)
  expect(active).toEqual([L.rotation, L.socks])
  expect(html).not.toContain('id="ns-minutes"')
})

it("shows the saved alternate SOCKS endpoint instead of the default port", () => {
  const html = reopen([saved.replace("socks5://", "socks5h://").replace(":9696", ":1080")])
  const active = [...html.matchAll(/<button\b[^>]*aria-pressed="true"[^>]*>([\s\S]*?)<\/button>/g)]
    .map(([, text]) => text)
  expect(active).toEqual([L.sticky, "socks5h 1080"])
})

it("uses Keep for a mixed set of saved SOCKS endpoint variants", () => {
  const html = reopen([saved, saved.replace("ab12", "cd34").replace(":9696", ":1080")], [0, 1])
  const active = [...html.matchAll(/<button\b[^>]*aria-pressed="true"[^>]*>([\s\S]*?)<\/button>/g)]
    .map(([, text]) => text)
  expect(active).toEqual([L.sticky, L.keep])
})

it("keeps the panel open when the API reports a rejected proxy line", async () => {
  vi.mocked(saveProxiesLines).mockResolvedValue({
    proxies: [saved], health: [], enabled: true, rotating: 0,
    errors: [{ line: 2, error: "synthetic format refused" }],
  })
  const onClose = vi.fn()
  renderToStaticMarkup(createElement(NoshadowPanel, { proxies: [saved], marks, onClose }))
  buttons.find((button) => button.children === L.generate)!.onClick!()
  await vi.waitFor(() => expect(notify.warn).toHaveBeenCalledWith("Synthetic format refused."))
  expect(onClose).not.toHaveBeenCalled()
  expect(notify.ok).not.toHaveBeenCalled()
})

it("refuses a bulk country change that merges endpoints despite different rotation URLs", () => {
  const proxies = [
    saved.replace("country-GB", "country-US") + " https://rotation.invalid/first",
    saved.replace("country-GB", "country-DE") + " https://rotation.invalid/second",
  ]
  editingState.countries = ["GB"]
  const onClose = vi.fn()
  renderToStaticMarkup(createElement(NoshadowPanel, { proxies, marks, editing: [0, 1], onClose }))
  buttons.find((button) => button.children === L.apply)!.onClick!()
  expect(saveProxiesLines).not.toHaveBeenCalled()
  expect(notify.warn).toHaveBeenCalledWith(PROXIES_TOAST.wouldMerge)
  expect(onClose).not.toHaveBeenCalled()
  expect(notify.ok).not.toHaveBeenCalled()
})

it.each([0, 45])("country-only Apply keeps explicit time-%i and an absent session", (minutes) => {
  const line = `http://fixture-country-US-time-${minutes}:synthetic@proxy.noshadow.pro:6969`
  editingState.countries = ["GB"]
  renderToStaticMarkup(createElement(NoshadowPanel, { proxies: [line], marks, editing: [0], onClose: vi.fn() }))
  buttons.find((button) => button.children === L.apply)!.onClick!()
  expect(saveProxiesLines).toHaveBeenCalledExactlyOnceWith([line.replace("country-US", "country-GB")], marks)
})
