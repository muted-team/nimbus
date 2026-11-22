import { createElement, type PropsWithChildren } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

// The Node runner has no portal target; keep the row and icons real.
vi.mock("@/components/ui/context-menu", async (original) => ({
  ...await original<typeof import("@/components/ui/context-menu")>(),
  ContextMenuContent: ({ children }: PropsWithChildren) => createElement("section", { "data-menu": "context" }, children),
  ContextMenuItem: ({ children, disabled }: PropsWithChildren<{ disabled?: boolean }>) => createElement("button", { disabled }, children),
}))
vi.mock("@/components/ui/dropdown-menu", async (original) => ({
  ...await original<typeof import("@/components/ui/dropdown-menu")>(),
  DropdownMenuContent: ({ children }: PropsWithChildren) => createElement("section", { "data-menu": "dropdown" }, children),
  DropdownMenuItem: ({ children, disabled }: PropsWithChildren<{ disabled?: boolean }>) => createElement("button", { disabled }, children),
}))

import { ProxyTableRow, type ProxyRowActions } from "./proxy-row"
import { proxyActions } from "./actions"
import { NOSHADOW_LABEL } from "./labels"
import type { ProxyRow } from "./filter"

const row: ProxyRow = {
  index: 0, proxy: "proxy.noshadow.pro:9696", state: "ok", enabled: true,
  noshadow: { country: "GB", minutes: 45 },
}
const actions: ProxyRowActions = {
  menu: (rows) => proxyActions(rows, vi.fn()),
  toggleLogin: vi.fn(), toggleRegistration: vi.fn(), togglePublish: vi.fn(),
}

it("offers Configure NoShadow in both single-row menus", () => {
  const html = renderToStaticMarkup(createElement(ProxyTableRow, {
    row, rotateBusy: false, actions, selected: true,
    onPick: vi.fn(), selectionCount: 1, bulk: [],
  }))
  const menus = [...html.matchAll(/<section data-menu="(?:context|dropdown)">([\s\S]*?)<\/section>/g)]
  expect(menus).toHaveLength(2)
  for (const [, menu] of menus) expect(menu).toContain(NOSHADOW_LABEL.bulk)
  expect(menus[0][1].replaceAll("dropdown-menu", "context-menu")).toBe(menus[1][1])
})

it("keeps the same disabled IP actions in both menus of a disabled proxy", () => {
  const html = renderToStaticMarkup(createElement(ProxyTableRow, {
    row: { ...row, enabled: false, rotating: true }, rotateBusy: false, actions,
    selected: false, onPick: vi.fn(), selectionCount: 0, bulk: [],
  }))
  const menus = [...html.matchAll(/<section data-menu="(?:context|dropdown)">([\s\S]*?)<\/section>/g)]
  const buttons = (menu: string) => [...menu.matchAll(/<button([^>]*)>([\s\S]*?)<\/button>/g)]
    .map(([, attrs, inner]) => ({ disabled: attrs.includes('disabled=""'), inner }))
  expect(buttons(menus[0][1])).toEqual(buttons(menus[1][1]))
  expect(buttons(menus[0][1]).filter((button) => button.disabled)).toHaveLength(2)
})
