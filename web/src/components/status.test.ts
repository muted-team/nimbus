import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it } from "vitest"

import { StatusBadge, StatusDot, toneText } from "./status"
import { Progress } from "./ui/progress"

it("активный прогон использует акцент в статусе, точке и полосе прогресса", () => {
  // SSR in a .test.ts file: this component's props require children explicitly.
  // oxlint-disable-next-line react/no-children-prop
  const badge = renderToStaticMarkup(createElement(StatusBadge, { tone: "live", children: "Идёт" }))
  const dot = renderToStaticMarkup(createElement(StatusDot, { tone: "live", pulse: true }))
  const progress = renderToStaticMarkup(createElement(Progress, { value: 50 }))

  expect(toneText.live).toBe("text-primary")
  expect(badge).toContain("bg-primary/15 text-primary")
  expect(dot).toContain("bg-primary")
  expect(progress).toMatch(/data-slot="progress-indicator"[^>]*bg-primary/)
  for (const html of [badge, dot, progress]) expect(html).not.toMatch(/(?:bg|text)-info/)
})

it("ошибки и предупреждения сохраняют свои смысловые цвета", () => {
  expect(toneText.bad).toBe("text-destructive")
  expect(toneText.warn).toBe("text-warning")
  expect(renderToStaticMarkup(createElement(StatusDot, { tone: "ok" }))).toContain("bg-success")
})
