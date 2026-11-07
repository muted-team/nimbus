import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { keys, queryClient } from "@/api/query-client"
import { fromServer } from "./form-model"
import { useFormStore } from "./form-store"
import { useCampaignLauncher, type CampaignLauncher } from "./launcher"

const mocks = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  confirm: vi.fn(),
  navigate: vi.fn(),
  error: vi.fn(),
  slots: vi.fn(),
}))

vi.mock("wouter", () => ({ useLocation: () => ["/", mocks.navigate] }))
vi.mock("@/api/accounts", () => ({ useAccounts: () => ({ data: { accounts: [{ username: "fixture" }] } }) }))
vi.mock("@/api/campaign", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/campaign")>(),
  useCampaignStatus: () => ({ data: { status: "idle" } }),
  startCampaign: mocks.start,
  stopCampaign: mocks.stop,
}))
vi.mock("@/components/confirm", () => ({ confirm: mocks.confirm }))
vi.mock("@/lib/notify", () => ({ notify: { ok: vi.fn(), info: vi.fn(), warn: vi.fn(), error: mocks.error } }))
vi.mock("./slot-files", () => ({ fetchSlotFiles: mocks.slots }))

function Capture({ onCapture }: { onCapture: (control: CampaignLauncher) => void }) {
  onCapture(useCampaignLauncher())
  return null
}

function launcher(): CampaignLauncher {
  const controls: CampaignLauncher[] = []
  renderToStaticMarkup(createElement(Capture, { onCapture: (control) => controls.push(control) }))
  const captured = controls[0]
  if (!captured) throw new Error("Launcher was not rendered")
  return captured
}

beforeEach(() => {
  vi.clearAllMocks()
  queryClient.clear()
  queryClient.setQueryData(keys.campaignStatus, { status: "idle" })
  useFormStore.setState({
    values: fromServer({ slots: ["fixture"], posts_per_account: 1 }),
    saved: null,
    showErrors: false,
    pendingFocus: false,
  })
  mocks.slots.mockResolvedValue(new Map([["fixture", { path: "fixture", exists: true, photos: 10, videos: 0 }]]))
  mocks.start.mockResolvedValue({ ok: true })
  mocks.stop.mockResolvedValue({ status: "stopping" })
  mocks.confirm.mockResolvedValue(true)
})

afterEach(() => queryClient.clear())

it("быстрые клики и запуск из второго экрана отправляют один запрос", async () => {
  let release: () => void = () => {}
  const pending = new Promise<void>((resolve) => { release = resolve })
  mocks.start.mockImplementation(async () => {
    await pending
    return { ok: true }
  })
  const first = launcher()
  const second = launcher()
  const attempts = [
    first.launch(undefined, { confirm: false }),
    first.launch(undefined, { confirm: false }),
    second.launch(undefined, { confirm: false }),
  ]
  try {
    await vi.waitFor(() => expect(mocks.start).toHaveBeenCalled())
    expect(mocks.start).toHaveBeenCalledTimes(1)
  } finally {
    release()
    await Promise.all(attempts)
  }
})

it("во время подтверждения повторный запуск не открывает второе окно", async () => {
  let release: (ok: boolean) => void = () => {}
  mocks.confirm.mockImplementation(() => new Promise<boolean>((resolve) => { release = resolve }))
  const first = launcher()
  const second = launcher()
  const attempts = [first.launch(), second.launch()]
  try {
    await vi.waitFor(() => expect(mocks.confirm).toHaveBeenCalled())
    expect(mocks.confirm).toHaveBeenCalledTimes(1)
  } finally {
    release(false)
    await Promise.all(attempts)
  }
  expect(mocks.start).not.toHaveBeenCalled()
  mocks.confirm.mockResolvedValue(true)
  expect(await second.launch()).toBe(true)
})

it("сбой подсчёта файлов показывает ошибку и освобождает запуск", async () => {
  const error = new Error("fixture lookup failed")
  mocks.slots.mockRejectedValueOnce(error)
  const control = launcher()
  expect(await control.launch(undefined, { confirm: false })).toBe(false)
  expect(mocks.error).toHaveBeenCalledWith(error, expect.any(String))
  expect(await control.launch(undefined, { confirm: false })).toBe(true)
})

it("прогон из другого окна во время подтверждения не запускается повторно", async () => {
  mocks.confirm.mockImplementation(async () => {
    queryClient.setQueryData(keys.campaignStatus, { status: "running" })
    return true
  })
  expect(await launcher().launch()).toBe(false)
  expect(mocks.start).not.toHaveBeenCalled()
})

it("остановка общая для разных экземпляров кнопок", async () => {
  let release: () => void = () => {}
  mocks.stop.mockImplementation(() => new Promise<void>((resolve) => { release = resolve }))
  const first = launcher()
  const second = launcher()
  const attempts = [first.stop(), second.stop()]
  try {
    expect(mocks.stop).toHaveBeenCalledTimes(1)
  } finally {
    release()
    await Promise.all(attempts)
  }
})
