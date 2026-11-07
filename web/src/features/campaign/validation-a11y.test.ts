import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { fromServer } from "./form-model"

// SSR reads Zustand's initial snapshot, so inject a form fixture at the hook
// boundary while rendering the real panels, inputs and validation messages.
const state = {
  values: fromServer({ slots: ["fixture"] }),
  showErrors: true,
  pendingFocus: false,
}
vi.mock("./form-store", () => ({
  useFormStore: (select: (state: unknown) => unknown) => select(state),
  updateForm: vi.fn(),
}))
vi.mock("@/api/accounts", () => ({ useAccounts: () => ({ data: { accounts: [] } }) }))
vi.mock("@/api/misc", () => ({ useMediaLibrary: () => ({ data: { root: "media", folders: [] } }) }))
vi.mock("./slot-files", () => ({ useSlotFiles: () => new Map() }))
vi.mock("@/lib/native", () => ({ hasNativeWindow: () => false, onNativeReady: vi.fn() }))
vi.mock("@/hooks/use-folder-upload", () => ({ useFolderUpload: () => ({ state: null, upload: vi.fn() }) }))

import { ContentPanel } from "./content-panel"
import { ParamsPanel } from "./params-panel"

beforeEach(() => {
  state.values = {
    ...fromServer({ slots: ["fixture"] }),
    posts: "0",
    delayMin: "2",
    delayMax: "1",
    cleanup: true,
    cleanupMode: "count",
    cleanupCount: "0",
    repeat: true,
    repeatMin: "2",
    repeatMax: "1",
  }
  state.showErrors = true
})

afterEach(() => { state.values = fromServer({ slots: ["fixture"] }) })

it("у каждого ошибочного параметра есть ссылка на его текст ошибки", () => {
  const html = renderToStaticMarkup(createElement(ParamsPanel))
  const errors = [...html.matchAll(/<div\b[^>]*data-slot="field-error"[^>]*>/g)].map(([tag]) => tag)
  expect(errors).toHaveLength(4)
  for (const tag of errors) {
    const id = tag.match(/\bid="([^"]+)"/)?.[1]
    expect(id).toBeTruthy()
    const described = [...html.matchAll(/<input\b[^>]*>/g)]
      .map(([input]) => input)
      .filter((input) => input.includes(`aria-describedby="${id}"`))
    expect(described.length).toBeGreaterThan(0)
    for (const input of described) expect(input).toContain('aria-invalid="true"')
  }
})

it("обе границы ошибочного диапазона связаны с одной подсказкой", () => {
  const html = renderToStaticMarkup(createElement(ParamsPanel))
  for (const field of ["delay", "repeat"]) {
    const inputs = [...html.matchAll(/<input\b[^>]*>/g)]
      .map(([input]) => input)
      .filter((input) => input.includes(`aria-describedby="camp-${field}-error"`))
    expect(inputs).toHaveLength(2)
  }
})

it("до попытки запуска нет ошибок и ссылок на отсутствующие подсказки", () => {
  state.showErrors = false
  const html = renderToStaticMarkup(createElement(ParamsPanel))
  expect(html).not.toContain('data-slot="field-error"')
  expect(html).not.toContain("aria-describedby")
  expect(html).not.toContain('aria-invalid="true"')
})

it("исправление параметров убирает ошибки и ссылки на них", () => {
  state.values = fromServer({ slots: ["fixture"] })
  const html = renderToStaticMarkup(createElement(ParamsPanel))
  expect(html).not.toContain('data-slot="field-error"')
  expect(html).not.toContain("aria-describedby")
  expect(html).not.toContain('aria-invalid="true"')
})

it.each([{ photoSlots: [""] }, { photoSlots: [] as string[] }])("ошибка папок относится к пути и кнопке добавления ($photoSlots)", ({ photoSlots }) => {
  state.values.photoSlots = photoSlots
  const html = renderToStaticMarkup(createElement(ContentPanel))
  expect(html).toMatch(/data-slot="field-error"[^>]*id="camp-folders-error"/)
  const controls = [...html.matchAll(/<(?:input|button)\b[^>]*data-field="folders"[^>]*>/g)]
    .map(([tag]) => tag)
  expect(controls).toHaveLength(photoSlots.length + 1)
  for (const control of controls) {
    expect(control).toContain('aria-describedby="camp-folders-error"')
    expect(control).toContain('aria-invalid="true"')
  }
})
