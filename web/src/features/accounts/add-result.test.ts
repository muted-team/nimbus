import { describe, expect, it } from "vitest"

import type { BulkAddResponse } from "@/api/types"

import { addedToast } from "./add-result"
import { ACC_TOAST, replacedWords } from "./labels"

/* Тост после вставки списка: вставленный второй раз аккаунт — не новый, о
   подмене полей надо сказать. Имён аккаунтов в тосте нет, поля называются
   словами. */

const res = (extra: Partial<BulkAddResponse> & { updated?: unknown }): BulkAddResponse =>
  ({ added: [], errors: [], ...extra }) as BulkAddResponse

describe("тост вставки списка", () => {
  it("одни новые — тот же текст, что был", () => {
    expect(addedToast(res({ added: ["a", "b"] }))).toEqual({
      text: "Добавлено аккаунтов: 2.",
      lines: undefined,
    })
  })

  it("поле updated сервер не прислал — читаем как раньше", () => {
    expect(addedToast(res({ added: ["a"] }))?.text).toBe(ACC_TOAST.added(1))
  })

  it("только перезаписи — обновлённые не считаются добавленными", () => {
    expect(addedToast(res({ updated: [{ username: "old", replaced: ["password"] }] }))).toEqual({
      text: "Обновлено аккаунтов: 1.",
      lines: ["Заменены: пароль."],
    })
  })

  it("и новые, и старые — оба числа", () => {
    const t = addedToast(
      res({
        added: ["new"],
        updated: [{ username: "old", replaced: ["totp_secret", "password"] }],
      })
    )
    expect(t?.text).toBe("Добавлено аккаунтов: 1. Обновлено аккаунтов: 1.")
    expect(t?.lines).toEqual(["Заменены: код 2FA, пароль."])
  })

  it("поля соседних аккаунтов не повторяются", () => {
    const t = addedToast(
      res({
        updated: [
          { username: "a", replaced: ["password", "email"] },
          { username: "b", replaced: ["password"] },
        ]
      })
    )
    expect(t?.lines).toEqual(["Заменены: пароль, почта."])
  })

  it("нечего сказать — тоста нет", () => {
    expect(addedToast(res({ errors: [{ line: 1, reason: "битая строка" }] }))).toBeNull()
    expect(addedToast(res({}))).toBeNull()
  })

  it("незнакомое поле в тост не просачивается", () => {
    expect(replacedWords(["password", "avatar"])).toEqual(["пароль"])
    expect(addedToast(res({ updated: [{ username: "a", replaced: ["secret"] }] }))?.lines).toBeUndefined()
  })
})
