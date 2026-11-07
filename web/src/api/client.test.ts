/// <reference types="node" />
import { createServer, type Server } from "node:http"
import { once } from "node:events"
import { afterAll, beforeAll, describe, expect, it } from "vitest"
import { api, ApiError, errorText, onAuthRequired } from "./client"

describe("HTTP-ответ дочитывается в пределах таймаута", () => {
  let server: Server
  let base: string
  const timers = new Set<ReturnType<typeof setTimeout>>()

  beforeAll(async () => {
    server = createServer((req, res) => {
      if (req.url === "/slow-body") {
        res.writeHead(200, { "Content-Type": "application/json" })
        res.flushHeaders()
        const timer = setTimeout(() => {
          timers.delete(timer)
          res.end('{"ok":true}')
        }, 200)
        timers.add(timer)
        return
      }
      if (req.url === "/html-error") {
        res.writeHead(502, { "Content-Type": "text/html" })
        res.end("<html>fixture failure</html>")
        return
      }
      if (req.url === "/auth") {
        res.writeHead(401, { "Content-Type": "application/json" })
        res.end('{"auth":true,"error":"нужен пароль"}')
        return
      }
      res.writeHead(200, { "Content-Type": "application/json" })
      res.end(req.url === "/broken-body" ? '{"ok":' : '{"ok":true}')
    })
    server.listen(0, "127.0.0.1")
    await once(server, "listening")
    const address = server.address()
    if (!address || typeof address === "string") throw new Error("fixture has no port")
    base = `http://127.0.0.1:${address.port}`
  })

  afterAll(async () => {
    timers.forEach(clearTimeout)
    server.closeAllConnections()
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  })

  it("прерывает ответ, заголовки которого уже пришли", async () => {
    await expect(api.get(`${base}/slow-body`, { timeout: 50 })).rejects.toMatchObject({
      name: "ApiError", status: 0, message: "превышено время ожидания (0 с)",
    })
  })

  it("не считает оборванный JSON успешным запросом", async () => {
    await expect(api.post(`${base}/broken-body`)).rejects.toMatchObject({
      name: "ApiError", status: 200, message: "сервер вернул некорректный ответ",
    })
  })

  it("сохраняет HTTP-статус ошибки без JSON", async () => {
    await expect(api.get(`${base}/html-error`)).rejects.toMatchObject({
      name: "ApiError", status: 502, message: "HTTP 502",
    })
  })

  it("читает обычный JSON и сообщает о требовании пароля", async () => {
    expect(await api.get(`${base}/ok`)).toEqual({ ok: true })
    let calls = 0
    const unsubscribe = onAuthRequired(() => { calls += 1 })
    try {
      await expect(api.get(`${base}/auth`)).rejects.toBeInstanceOf(ApiError)
      expect(calls).toBe(1)
    } finally {
      unsubscribe()
    }
  })
})

describe("ошибки описывают проблему без указаний пользователю", () => {
  it.each([
    ["сервер не поддерживает выбранный профиль браузера — обновите сервер", "Сервер не поддерживает выбранный профиль браузера."],
    ["сервер не подтвердил профиль браузера — обновите сервер", "Сервер не подтвердил профиль браузера."],
    ["сервер перегружен, попробуйте позже", "Сервер перегружен."],
    ["прокси не отвечает — проверьте адрес и порт", "Прокси не отвечает."],
    ["TikTok не выдал токен сессии — смените IP или сделайте паузу", "TikTok не выдал токен сессии."],
  ])("%s", (raw, expected) => expect(errorText(new Error(raw))).toBe(expected))
  it("сохраняет причину, код, префикс и неизвестные ошибки", () => {
    expect(errorText(new Error("TikTok отклонил пост (код 1004)"), "Не опубликовано")).toBe("Не опубликовано: TikTok отклонил пост (код 1004).")
    expect(errorText("неизвестный формат фото")).toBe("Неизвестный формат фото.")
  })
})
