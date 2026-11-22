import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Settings } from "@/api/types"

const fixture = vi.hoisted(() => ({
  settings: {
    browser_profile: "firefox155", browser_profile_active: "firefox155",
    browser_profiles: ["chrome152", "firefox155"],
    server: { url: "https://service.example", default: "https://service.example", custom: false },
    threads: 2, threads_max: 10, proxy_on_death: "swap", server_wait_min: 30, server_wait_max: 240,
    host: "127.0.0.1", port: 8740, bound: { host: "127.0.0.1", port: 8740 },
    phone: { on: true, active: true, supported: true, connected: false, links: ["http://192.168.1.5:8740"] },
    password: { available: true, set: true, min_len: 6, required: false },
  } as Settings,
}))

vi.mock("@/api/misc", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/misc")>(),
  useSettings: () => ({ data: fixture.settings }),
}))
// Theme is supplied by a browser bootstrap script, not the settings API.
vi.mock("@/app/theme", () => ({ useTheme: () => ({ mode: "system", resolved: "light" }), setTheme: vi.fn() }))

import SettingsPage from "./settings-page"

function render() {
  return renderToStaticMarkup(createElement(QueryClientProvider, { client: new QueryClient() },
    createElement(SettingsPage)))
}

describe("one coherent device-access block", () => {
  beforeEach(() => {
    fixture.settings.password.set = true
    fixture.settings.phone.active = true
    fixture.settings.phone.on = true
    fixture.settings.phone.supported = true
    fixture.settings.host = "127.0.0.1"
    fixture.settings.bind_explicit = true
    fixture.settings.bound.host = "127.0.0.1"
  })

  it("groups password, bind, port, phone access and links without duplicate settings cards", () => {
    const html = render()
    const blocks = html.match(/<section\b[^>]*data-slot="panel"[^>]*>[\s\S]*?<\/section>/g) ?? []
    const access = blocks.filter((block) => block.includes("Доступ с других устройств"))
    expect(access).toHaveLength(1)
    for (const content of ["settings-password", "settings-port", "Адрес привязки", "settings-phone", "http://192.168.1.5:8740", "Внешний IP или домен"])
      expect(access[0]).toContain(content)
    expect(blocks.some((block) => /<h2[^>]*>[\s\S]*?<span[^>]*>Подключить телефон<\/span>/.test(block))).toBe(false)
    expect(blocks.some((block) => /<h2[^>]*>[\s\S]*?<span[^>]*>Адрес<\/span>/.test(block))).toBe(false)
  })

  it("describes a stored password honestly without pretending to recover its plaintext", () => {
    const html = render()
    expect(html).toContain("Пароль задан.")
    expect(html).toMatch(/<input[^>]*id="settings-password"[^>]*value=""/)
    expect(html).not.toContain("••••")
  })

  it("does not enable LAN before a password has been saved", () => {
    fixture.settings.password.set = false
    fixture.settings.phone.active = false
    fixture.settings.phone.on = false
    const html = render()
    const phoneSwitch = html.match(/<[^>]*role="switch"[^>]*>/)?.[0]
    expect(phoneSwitch).toContain('aria-disabled="true"')
    expect(html).toContain("Сначала задайте пароль")
  })

  it("leaves unsupported LAN control disabled instead of claiming it is live", () => {
    fixture.settings.phone.supported = false
    fixture.settings.phone.active = false
    fixture.settings.phone.on = false
    const html = render()
    const phoneSwitch = html.match(/<[^>]*role="switch"[^>]*>/)?.[0]
    expect(phoneSwitch).toContain('aria-disabled="true"')
    expect(html).not.toContain("Сетевая привязка уже активна")
  })

  it("does not present the legacy wildcard default as an intentional remote bind", () => {
    fixture.settings.host = "0.0.0.0"
    fixture.settings.bind_explicit = false
    const html = render()
    expect(html).toMatch(/data-slot="select-value"[^>]*>127\.0\.0\.1 — этот компьютер/)
    expect(html).not.toContain("Сохранено для следующего запуска")
  })

  it("requires an explicit true flag before displaying an intentional wildcard", () => {
    fixture.settings.host = "0.0.0.0"
    fixture.settings.phone.on = false
    fixture.settings.phone.active = false
    delete fixture.settings.bind_explicit
    const html = render()
    expect(html).toMatch(/data-slot="select-value"[^>]*>127\.0\.0\.1 — этот компьютер/)
    expect(html).not.toContain("Сохранено для следующего запуска")
    const removeButton = html.match(/<button[^>]*>Снять<\/button>/)?.[0]
    expect(removeButton).toBeDefined()
    expect(removeButton).not.toContain('disabled=""')
  })

  it("warns that internet access needs VPN or HTTPS rather than sending a password over plain HTTP", () => {
    expect(render()).toContain("VPN или HTTPS")
  })
})
