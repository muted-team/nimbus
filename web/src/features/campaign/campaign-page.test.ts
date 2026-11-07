import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

vi.mock("@/api/campaign", () => ({
  useCampaignForm: () => ({ data: {} }),
  useCampaignStatus: () => ({ data: { status: "stopped", restored: true } }),
}))
vi.mock("./form-store", () => ({
  useFormStore: (select: (s: unknown) => unknown) => select({ values: {}, pendingFocus: false }),
  hydrateForm: vi.fn(), useFormAutosave: vi.fn(),
}))
vi.mock("./launcher", () => ({ useCampaignLauncher: () => ({ live: false, busy: false }) }))
vi.mock("@/hooks/use-hotkey", () => ({ useHotkey: vi.fn() }))
vi.mock("./content-panel", () => ({ ContentPanel: () => "content-editor" }))
vi.mock("./processing-panel", () => ({ ProcessingPanel: () => "processing-editor" }))
vi.mock("./params-panel", () => ({ ParamsPanel: () => "publish-parameters" }))
vi.mock("./launch-panel", () => ({ LaunchPanel: () => "publish-launch" }))
vi.mock("./first-run", () => ({ FirstRun: () => "first-run-checklist" }))
vi.mock("./results-panel", () => ({ CampaignResults: () => "previous-run-report" }))
vi.mock("./campaign-progress", () => ({ CampaignProgress: () => "previous-run-progress" }))

import CampaignPage from "./campaign-page"

it("публикация содержит параметры и запуск, без редактора контента, шагов и прошлого отчёта", () => {
  const html = renderToStaticMarkup(createElement(CampaignPage))
  expect(html).toContain("publish-parameters")
  expect(html).toContain("publish-launch")
  for (const removed of ["content-editor", "processing-editor", "first-run-checklist", "previous-run-report", "previous-run-progress"]) {
    expect(html).not.toContain(removed)
  }
})
