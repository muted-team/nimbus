import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { expect, it, vi } from "vitest"

// Render the actual login field in its error state without using credentials.
vi.mock("react", async (importOriginal) => {
  const react = await importOriginal<typeof import("react")>()
  return {
    ...react,
    useState: ((initial: unknown) => {
      const state = react.useState(initial)
      return initial === "" ? ["Ошибка тестового входа", state[1]] : state
    }) as typeof react.useState,
  }
})

import { LoginScreen } from "./login-screen"

it("поле входа связано с показанной ошибкой", () => {
  const html = renderToStaticMarkup(createElement(LoginScreen))
  const input = html.match(/<input\b[^>]*id="password"[^>]*>/)?.[0]
  const error = html.match(/<div\b[^>]*data-slot="field-error"[^>]*>/)?.[0]
  expect(error).toBeDefined()
  expect(html).toContain("Ошибка тестового входа")
  const id = error?.match(/\bid="([^"]+)"/)?.[1]
  expect(id).toBeTruthy()
  expect(input).toContain(`aria-describedby="${id}"`)
  expect(input).toContain('aria-invalid="true"')
})
