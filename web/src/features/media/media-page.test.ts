import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

vi.mock("wouter", () => ({ useLocation: () => ["/media", vi.fn()], useParams: () => ({}) }))
vi.mock("@/api/misc", () => ({ useMediaLibrary: () => ({ data: { folders: [] }, isSuccess: true }) }))
vi.mock("@/api/campaign", () => ({ useCampaignForm: () => ({ data: {} }) }))
vi.mock("@/features/campaign/form-store", () => ({
  useFormStore: (select: (s: unknown) => unknown) => select({ values: { media: "photo", photoSlots: [] } }),
  hydrateForm: vi.fn(), useFormAutosave: vi.fn(), updateForm: vi.fn(),
}))
vi.mock("@/features/campaign/content-panel", () => ({ ContentPanel: () => "canonical-content-editor" }))
vi.mock("@/features/campaign/processing-panel", () => ({ ProcessingPanel: () => "creative-processing" }))
vi.mock("@/hooks/use-hotkey", () => ({ useHotkey: vi.fn() }))
vi.mock("@/hooks/use-folder-upload", () => ({ useFolderUpload: () => ({ state: null }) }))
vi.mock("@/components/state-view", () => ({
  QueryView: ({ children }: { children: () => unknown }) => children(),
  ErrorView: () => "load-error", LoadingRows: () => "loading",
}))
import MediaPage from "./media-page"

it("креативы объединяют папки, контент и обработку в одном разделе", () => {
  const html = renderToStaticMarkup(createElement(MediaPage))
  expect(html).toContain("canonical-content-editor")
  expect(html).toContain("creative-processing")
  expect(html).toContain("Библиотека")
})
