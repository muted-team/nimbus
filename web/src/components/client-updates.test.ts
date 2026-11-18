import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { expect, it } from "vitest"
import { ClientUpdates } from "./client-updates"

it("browser mode points only at public client Releases without promising installation", () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const html = renderToStaticMarkup(
    createElement(QueryClientProvider, { client }, createElement(ClientUpdates))
  )
  expect(html).toContain("Обновления Nimbus")
  expect(html).toContain("GitHub Releases")
  expect(html).toContain("настольном приложении")
  expect(html).not.toContain("Перезапустить и обновить")
  expect(html).not.toContain("Скачать обновление")
  expect(html).not.toContain("Проверить обновления")
  client.clear()
})
