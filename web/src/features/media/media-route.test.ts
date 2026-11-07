import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"
import { Route, Router } from "wouter"
import { useHashLocation } from "wouter/use-hash-location"

const folders = vi.hoisted(() => [
  { name: "Скидка 50%", path: "fixture/discount", photos: 1, videos: 0, preview: [] },
  { name: "Фото %20", path: "fixture/percent", photos: 1, videos: 0, preview: [] },
  { name: "A#B?C", path: "fixture/reserved", photos: 1, videos: 0, preview: [] },
])

vi.mock("@/api/misc", () => ({
  useMediaLibrary: () => ({ data: { folders }, isSuccess: true }),
  useMediaFiles: () => ({ data: [] }),
}))
vi.mock("@/api/campaign", () => ({ useCampaignForm: () => ({ data: {} }) }))
vi.mock("@/features/campaign/form-store", () => ({
  useFormStore: (select: (s: unknown) => unknown) => select({ values: { media: "photo", photoSlots: [] } }),
  hydrateForm: vi.fn(), useFormAutosave: vi.fn(), updateForm: vi.fn(),
}))
vi.mock("@/features/campaign/content-panel", () => ({ ContentPanel: () => "content-editor" }))
vi.mock("@/features/campaign/processing-panel", () => ({ ProcessingPanel: () => "processing-editor" }))
vi.mock("@/hooks/use-hotkey", () => ({ useHotkey: vi.fn() }))
vi.mock("@/hooks/use-folder-upload", () => ({ useFolderUpload: () => ({ state: null }) }))
vi.mock("@/components/state-view", () => ({
  QueryView: ({ children }: { children: () => unknown }) => children(),
  ErrorView: () => "load-error", LoadingRows: () => "loading",
}))

import MediaPage from "./media-page"

function renderPath(ssrPath: string) {
  const route = { path: "/media/*?", children: createElement(MediaPage) }
  const router = { hook: useHashLocation, ssrPath, children: createElement(Route, route) }
  return renderToStaticMarkup(createElement(Router, router))
}

it("открывает папку с процентом в имени без повторного декодирования", () => {
  const html = renderPath(`/media/f/${encodeURIComponent(folders[0].name)}`)
  expect(html).toContain('aria-current="page">Скидка 50%')
  expect(html).not.toContain("content-editor")
})

it("буквальное %20 в имени не превращается в пробел", () => {
  const html = renderPath(`/media/f/${encodeURIComponent(folders[1].name)}`)
  expect(html).toContain('aria-current="page">Фото %20')
  expect(html).not.toContain("content-editor")
})

it("зарезервированные символы имени декодируются один раз", () => {
  const html = renderPath(`/media/f/${encodeURIComponent(folders[2].name)}`)
  expect(html).toContain('aria-current="page">A#B?C')
})

it("повреждённый адрес папки не роняет весь экран", () => {
  expect(() => renderPath("/media/f/%E0%A4%A")).not.toThrow()
  expect(renderPath("/media/f/%E0%A4%A")).toContain("Библиотека")
})
