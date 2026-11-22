import { createElement, Fragment, type PropsWithChildren, type ReactNode } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, expect, it, vi } from "vitest"

import { keys, queryClient } from "@/api/query-client"
import type { ProxiesResponse } from "@/api/types"

const controls = vi.hoisted(() => ({
  buttons: [] as { children?: ReactNode; onClick?: () => void }[],
  paste: null as ((event: { target: { value: string } }) => void) | null,
}))
vi.mock("@/components/ui/button", async (original) => {
  const real = await original<typeof import("@/components/ui/button")>()
  return { ...real, Button: (props: Parameters<typeof real.Button>[0]) => {
    controls.buttons.push({ children: props.children, onClick: props.onClick as () => void })
    return createElement(real.Button, props)
  } }
})
vi.mock("@/components/ui/textarea", () => ({ Textarea: ({ onChange }: { onChange: typeof controls.paste }) => {
  controls.paste = onChange
  return null
} }))
vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({ children }: PropsWithChildren) => createElement(Fragment, null, children),
  SheetContent: ({ children }: PropsWithChildren) => createElement("section", null, children),
  SheetHeader: ({ children }: PropsWithChildren) => createElement("header", null, children),
  SheetTitle: ({ children }: PropsWithChildren) => createElement("h2", null, children),
  SheetDescription: ({ children }: PropsWithChildren) => createElement("p", null, children),
  SheetFooter: ({ children }: PropsWithChildren) => createElement("footer", null, children),
}))
vi.mock("@/api/proxies", () => ({ saveProxies: vi.fn(), checkProxies: vi.fn() }))
vi.mock("@/lib/notify", () => ({ notify: { ok: vi.fn(), warn: vi.fn(), error: vi.fn() } }))

import { saveProxies } from "@/api/proxies"
import { notify } from "@/lib/notify"
import { mutateProxies, useProxiesStore } from "./proxies-store"
import { NoshadowPanel } from "./noshadow-panel"
import { ProxyAddPanel } from "./proxy-add-panel"
import { ProxyEditPanel } from "./proxy-edit-panel"
import { NOSHADOW_LABEL, PROXY_ADD_LABEL, PROXY_EDIT_LABEL } from "./labels"

const proxies = ["http://fixture-country-US-session-ab12-time-45:synthetic@proxy.noshadow.pro:6969"]
const marks = { login: [0], publish: [], registration: [], off: [] }
const snapshot: ProxiesResponse = { proxies, health: [], enabled: true, rotating: 0, errors: [] }

beforeEach(() => {
  vi.resetAllMocks()
  queryClient.clear()
  useProxiesStore.setState({ mutating: false })
  controls.buttons = []
  controls.paste = null
})

function renderPanel(kind: string, onClose: () => void) {
  if (kind === "add") {
    renderToStaticMarkup(createElement(ProxyAddPanel, { proxies, ...marks, onClose, onNoshadow: vi.fn() }))
    controls.paste!({ target: { value: "http://new.invalid:8080" } })
    return controls.buttons.find((button) => Array.isArray(button.children) && button.children.includes(PROXY_ADD_LABEL.add))!.onClick!
  }
  if (kind === "edit") {
    renderToStaticMarkup(createElement(ProxyEditPanel, { proxies, ...marks, index: 0, addr: "synthetic", onClose }))
    return controls.buttons.find((button) => button.children === PROXY_EDIT_LABEL.save)!.onClick!
  }
  renderToStaticMarkup(createElement(NoshadowPanel, { proxies, marks, onClose }))
  return controls.buttons.find((button) => button.children === NOSHADOW_LABEL.generate)!.onClick!
}

it.each(["add", "edit", "NoShadow"])("the %s whole-list writer shares the guard and never closes on a refused write", async (kind) => {
  let release!: () => void
  const deletion = mutateProxies(proxies, () => new Promise<void>((resolve) => { release = resolve }))
  const onClose = vi.fn()
  const submit = renderPanel(kind, onClose)
  submit()
  await Promise.resolve()
  await Promise.resolve()
  expect(saveProxies).not.toHaveBeenCalled()
  expect(notify.ok).not.toHaveBeenCalled()
  expect(onClose).not.toHaveBeenCalled()
  release()
  await deletion
  let finish!: () => void
  vi.mocked(saveProxies).mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve(snapshot) }))
  submit()
  expect(saveProxies).toHaveBeenCalledTimes(1)
  const marking = vi.fn(async () => snapshot)
  expect(await mutateProxies(proxies, marking)).toBeNull()
  expect(marking).not.toHaveBeenCalled()
  finish()
  await vi.waitFor(() => expect(useProxiesStore.getState().mutating).toBe(false))
  expect(notify.ok).toHaveBeenCalledTimes(kind === "add" ? 0 : 1)
})

it.each(["add", "edit", "NoShadow"])("the %s writer refuses its stale snapshot after deletion completes", async (kind) => {
  const onClose = vi.fn()
  const submit = renderPanel(kind, onClose)
  queryClient.setQueryData<ProxiesResponse>(keys.proxies, { ...snapshot, proxies: [] })
  submit()
  await Promise.resolve()
  await Promise.resolve()
  expect(saveProxies).not.toHaveBeenCalled()
  expect(notify.ok).not.toHaveBeenCalled()
  expect(onClose).not.toHaveBeenCalled()
})
