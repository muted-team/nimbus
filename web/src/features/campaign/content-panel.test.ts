import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

import { fromServer } from "./form-model"

vi.mock("./form-store", () => ({
  useFormStore: (select: (s: unknown) => unknown) => select({
    values: fromServer({ slots: ["fixture"], posts_per_account: 1 }),
    showErrors: false,
    pendingFocus: false,
  }),
  updateForm: vi.fn(),
}))
vi.mock("@/api/accounts", () => ({ useAccounts: () => ({ data: { accounts: [] } }) }))
vi.mock("@/api/misc", () => ({ useMediaLibrary: () => ({ data: { root: "media", folders: [] } }) }))
vi.mock("./slot-files", () => ({ useSlotFiles: () => new Map() }))
vi.mock("@/lib/native", () => ({ hasNativeWindow: () => false, onNativeReady: vi.fn() }))
vi.mock("@/hooks/use-folder-upload", () => ({ useFolderUpload: () => ({ state: null, upload: vi.fn() }) }))

import { ContentPanel } from "./content-panel"

it("путь папки имеет доступное имя", () => {
  const html = renderToStaticMarkup(createElement(ContentPanel))
  expect(html).toMatch(/<input[^>]*aria-label="Папка 1"/)
})

it("режим контента имеет доступное имя", () => {
  const html = renderToStaticMarkup(createElement(ContentPanel))
  expect(html).toMatch(/<button[^>]*role="combobox"[^>]*aria-label="Режим"/)
})
