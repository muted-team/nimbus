import { describe, expect, it } from "vitest"

import { remainingDraft, submissionText } from "./add-draft"

const rejected = { line: 2, reason: "не понял формат строки" }

describe("отправка куки целиком", () => {
  const cookies = '[\n{"name":"sid_guard","value":"synthetic"}\n]'
  it("не обрезает JSON по последнему переводу строки", () => {
    expect(submissionText(cookies, false)).toBe(cookies)
  })
  it("не отправляет незаконченный JSON во время набора", () => {
    expect(submissionText(cookies.slice(0, -1), false)).toBeNull()
    expect(submissionText(cookies.slice(0, -1), true)).toBe(cookies.slice(0, -1))
  })
  it("сохраняет изменённый JSON после ответа на предыдущую версию", () => {
    const latest = cookies.replace("synthetic", "new-synthetic")
    expect(remainingDraft(cookies, latest, [])).toEqual({text: latest, errors: [], retained: ""})
    expect(remainingDraft(cookies, cookies, [])).toEqual({text: "", errors: [], retained: ""})
  })
})

describe("черновик после добавления аккаунтов", () => {
  it("убирает принятые строки и сохраняет текст, дописанный во время запроса", () => {
    const sent = "accepted:fixture\nнепринятая строка\n"
    expect(remainingDraft(sent, sent + "новый текст", [rejected])).toEqual({
      text: "непринятая строка\nновый текст",
      errors: [{ ...rejected, line: 1 }],
      retained: "непринятая строка\n",
    })
  })

  it("полностью принятая пачка не стирает новый незаконченный ввод", () => {
    const sent = "accepted:fixture\n"
    expect(remainingDraft(sent, sent + "новый текст", [])).toEqual({
      text: "новый текст",
      errors: [],
      retained: "",
    })
  })

  it("не перезаписывает исправленную или заменённую во время запроса строку", () => {
    const latest = "исправленная строка"
    expect(remainingDraft("старая строка\n", latest, [{ ...rejected, line: 1 }])).toEqual({
      text: latest,
      errors: [],
      retained: "",
    })
  })

  it("не возвращает текст, который человек уже очистил", () => {
    expect(remainingDraft("старая строка\n", "", [{ ...rejected, line: 1 }])).toEqual({
      text: "",
      errors: [],
      retained: "",
    })
  })

  it("перенумеровывает ошибки после удаления принятых и пустых строк", () => {
    const sent = "accepted:fixture\r\n\r\nошибка один\r\nошибка два\r\n"
    expect(remainingDraft(sent, sent, [{ ...rejected, line: 3 }, { ...rejected, line: 4 }])).toEqual({
      text: "ошибка один\nошибка два",
      errors: [{ ...rejected, line: 1 }, { ...rejected, line: 2 }],
      retained: "ошибка один\nошибка два",
    })
  })

  it("дописанный символ в той же строке не превращает её в оторванный хвост", () => {
    const sent = "accepted:fixture"
    expect(remainingDraft(sent, sent + "_changed", [])).toEqual({
      text: sent + "_changed",
      errors: [],
      retained: "",
    })
  })

  it("перенос после вставленной строки отделяет новый ввод от принятой строки", () => {
    const sent = "accepted:fixture"
    expect(remainingDraft(sent, sent + "\nновый текст", [])).toEqual({
      text: "новый текст",
      errors: [],
      retained: "",
    })
  })

  it("не убирает пустую строку из более нового ввода", () => {
    const sent = "непринятая строка\n"
    expect(remainingDraft(sent, sent + "\nновый текст", [{ ...rejected, line: 1 }])).toEqual({
      text: "непринятая строка\n\nновый текст",
      errors: [{ ...rejected, line: 1 }],
      retained: "непринятая строка\n",
    })
  })

  it("не оставляет разделитель, когда вся пачка принята", () => {
    expect(remainingDraft("accepted:fixture\n", "accepted:fixture\n", [])).toEqual({
      text: "",
      errors: [],
      retained: "",
    })
  })
})
