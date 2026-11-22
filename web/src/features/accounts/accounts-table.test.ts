import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

import { AccountsTable } from "./accounts-table"
import type { RowHandlers } from "./account-row"
import { actionContext } from "./actions"
import { COLUMNS, gridTemplate } from "./columns"

it("header has independent identity columns and never treats avatar as a sortable metric", () => {
  const html = renderToStaticMarkup(createElement(AccountsTable, {
    accounts: [], busyNames: new Set<string>(), locked: false, selected: new Set<string>(),
    sort: "name", dir: "asc", onSort: vi.fn(), columns: COLUMNS,
    template: gridTemplate(COLUMNS, 3, false), onPickAll: vi.fn(),
    handlers: { actions: {} as RowHandlers["actions"], onOpen: vi.fn(), onPick: vi.fn(), onContextSelect: vi.fn() },
    selection: { ctx: actionContext([]), run: vi.fn() },
  }))
  expect(html.match(/role="columnheader"/g)).toHaveLength(COLUMNS.length + 2)
  expect(html).toContain("TikTok username")
  expect(html).toContain("Отображаемое имя")
  expect(html).toMatch(/role="columnheader"[^>]*>Аватар<\/div>/)
})
