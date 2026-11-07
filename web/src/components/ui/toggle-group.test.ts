import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"

import { ToggleGroup, ToggleGroupItem } from "./toggle-group"

function renderGroup(spacing: number) {
  const props = {
    spacing,
    children: [
      createElement(ToggleGroupItem, { key: "swap", value: "swap" }, "Сменить прокси"),
      createElement(ToggleGroupItem, { key: "stop", value: "stop" }, "Остановить поток"),
    ],
  }
  return renderToStaticMarkup(createElement(ToggleGroup, props))
}

it("раздельные варианты переносятся, не выходя за ширину строки", () => {
  const html = renderGroup(2)
  const group = html.slice(0, html.indexOf(">"))
  expect(group).toContain("max-w-full")
  expect(group).toContain("flex-wrap")
})

it("соединённые сегменты не разрываются переносом", () => {
  const html = renderGroup(0)
  const group = html.slice(0, html.indexOf(">"))
  expect(group).not.toContain("flex-wrap")
})
