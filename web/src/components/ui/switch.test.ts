import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"
import { Switch } from "./switch"

it("включённый переключатель использует индиго-токен и доступное состояние", () => {
  const html = renderToStaticMarkup(createElement(Switch, { checked: true }))
  expect(html).toContain('aria-checked="true"')
  expect(html).toContain('data-checked:bg-primary')
  expect(html).toContain('data-checked:bg-primary-foreground')
})
