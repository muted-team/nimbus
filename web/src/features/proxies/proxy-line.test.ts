import { describe, expect, it } from "vitest"

import { buildProxyLine, parseProxyLine } from "./proxy-line"

/* Строка прокси в списке — канонический вид, который делает разбор сервера
   при добавлении: схема://[логин:пароль@]хост:порт[ ссылка_смены_IP]. Другие
   форматы сюда попасть не могут — их знает только сервер. */

describe("разбор строки", () => {
  it("без учётки и без ссылки смены IP", () => {
    expect(parseProxyLine("socks5://1.2.3.4:1080")).toEqual({
      scheme: "socks5",
      login: "",
      password: "",
      host: "1.2.3.4",
      port: "1080",
      rotateUrl: "",
    })
  })

  it("с учёткой", () => {
    expect(parseProxyLine("http://user:pass@1.2.3.4:8080")).toEqual({
      scheme: "http",
      login: "user",
      password: "pass",
      host: "1.2.3.4",
      port: "8080",
      rotateUrl: "",
    })
  })

  it("с учёткой и со ссылкой смены IP", () => {
    expect(parseProxyLine("http://user:pass@1.2.3.4:8080 https://api.example.com/rotate?k=1")).toEqual({
      scheme: "http",
      login: "user",
      password: "pass",
      host: "1.2.3.4",
      port: "8080",
      rotateUrl: "https://api.example.com/rotate?k=1",
    })
  })

  it("хост IPv6 в квадратных скобках", () => {
    expect(parseProxyLine("socks5://[2001:db8::1]:1080")).toEqual({
      scheme: "socks5",
      login: "",
      password: "",
      host: "[2001:db8::1]",
      port: "1080",
      rotateUrl: "",
    })
  })

  it("пароль со спецсимволом показывается расшифрованным, а не процентами", () => {
    // сервер хранит учётку закодированной (в URL иначе нельзя), а поле правки
    // заведено, чтобы сверить пароль посимвольно — значит показываем как есть
    const got = parseProxyLine("http://myuser:gjfnix054%24@proxy.example.com:9696")
    expect(got?.password).toBe("gjfnix054$")
    expect(got?.login).toBe("myuser")
  })

  it("одинокий процент в пароле не роняет разбор", () => {
    const got = parseProxyLine("http://u:100%off@host.example:8080")
    expect(got?.password).toBe("100%off")
  })

  it("собранная строка уходит НЕ закодированной — кодирует сервер", () => {
    const got = parseProxyLine("http://myuser:gjfnix054%24@proxy.example.com:9696")
    expect(buildProxyLine(got!)).toBe("http://myuser:gjfnix054$@proxy.example.com:9696")
  })

  it("мусор — не разобралось, а не потерялось молча", () => {
    expect(parseProxyLine("это не прокси")).toBeNull()
    expect(parseProxyLine("host:port:user:pass")).toBeNull()
    expect(parseProxyLine("")).toBeNull()
  })
})

describe("сборка строки", () => {
  it("без учётки — тот же вид, что при разборе", () => {
    const fields = parseProxyLine("socks5://1.2.3.4:1080")!
    expect(buildProxyLine(fields)).toBe("socks5://1.2.3.4:1080")
  })

  it("с учёткой и ссылкой — round-trip", () => {
    const line = "http://user:pass@1.2.3.4:8080 https://api.example.com/rotate?k=1"
    expect(buildProxyLine(parseProxyLine(line)!)).toBe(line)
  })

  it("пустая ссылка смены IP не оставляет хвоста", () => {
    expect(
      buildProxyLine({ scheme: "http", login: "", password: "", host: "1.2.3.4", port: "80", rotateUrl: "  " })
    ).toBe("http://1.2.3.4:80")
  })

  it("собранную строку разбор снова читает так же", () => {
    const fields = { scheme: "socks4", login: "a", password: "b", host: "host.name", port: "1111", rotateUrl: "" }
    expect(parseProxyLine(buildProxyLine(fields))).toEqual(fields)
  })
})
