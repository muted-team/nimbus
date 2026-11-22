import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PasswordPanel } from "./password-panel"
import { generatePassword } from "./password-generator"

afterEach(() => vi.restoreAllMocks())

describe("password generation", () => {
  it("uses only CSPRNG bytes and maps all 64 symbols without modulo bias", () => {
    vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("Not cryptographic")
    })
    const entropy = vi.spyOn(crypto, "getRandomValues").mockImplementation(
      (array) => {
        const bytes = array as Uint8Array
        bytes.forEach((_, index) => { bytes[index] = index })
        return array
      }
    )
    expect(generatePassword(64)).toBe(
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    expect(entropy).toHaveBeenCalledOnce()
    expect(entropy.mock.calls[0][0]).toBeInstanceOf(Uint8Array)
  })

  it.each([6, 16, 32])(
    "meets minimum %i with at least 96 bits of entropy",
    (minLength) => {
      const value = generatePassword(minLength)
      expect(value).toHaveLength(Math.max(16, minLength))
      expect(value).toMatch(/^[A-Za-z0-9_-]+$/)
    }
  )
})

describe("Nimbus password draft", () => {
  it("offers icon-only reveal and deliberate generation beside a masked empty draft", () => {
    const html = renderToStaticMarkup(
      createElement(PasswordPanel, {
        password: { available: true, set: true, min_len: 6, required: false },
      })
    )
    expect(html).toMatch(/<input[^>]*type="password"[^>]*value=""/)
    for (const label of ["Показать новый пароль", "Сгенерировать пароль"]) {
      const button = html.match(new RegExp(`<button[^>]*aria-label="${label}"[^>]*>([\\s\\S]*?)<\\/button>`))
      expect(button, label).not.toBeNull()
      expect(button?.[1]).toContain("<svg")
      expect(button?.[1].replace(/<[^>]*>/g, "")).toBe("")
    }
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Задать<\/button>/)
  })
})
