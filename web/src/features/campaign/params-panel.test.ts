import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"
import { fromServer } from "./form-model"

vi.mock("./form-store", () => ({
  useFormStore: (select: (s: unknown) => unknown) => select({
    values: fromServer({ slots: ["fixture"], posts_per_account: 0, min_delay_ms: -1000 }),
    showErrors: true,
  }),
  updateForm: vi.fn(),
}))
import { ParamsPanel } from "./params-panel"

it("ошибка отмечает и поле, и контрол; поля объединены в FieldGroup", () => {
  const html = renderToStaticMarkup(createElement(ParamsPanel))
  expect(html).toContain('data-slot="field-group"')
  expect(html).toMatch(/data-slot="field"[^>]*data-invalid="true"/)
  expect(html).toContain('aria-invalid="true"')
  expect(html).toContain('data-slot="field-label"')
})

it("параметры остаются в одной панели без вложенных карточек", () => {
  const html = renderToStaticMarkup(createElement(ParamsPanel))
  expect(html).not.toContain("border-t-2")
  expect(html).not.toMatch(/data-slot="field"[^>]*class="[^"]*rounded-lg border/)
})
