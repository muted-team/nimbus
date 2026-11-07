import { describe, expect, it } from "vitest"

import type { Account, StudioCountersMap } from "@/api/types"

import { rowNumbers } from "./studio"

/* Числа в строке: студия точнее профиля, но профиль остаётся запасным
   источником. Ноль — это значение, а не «неизвестно»: подменять его нельзя. */

const acc = (username: string, extra: Partial<Account> = {}): Account => ({
  username,
  has_session: true,
  has_totp: false,
  has_email: false,
  avatar: null,
  profile: null,
  region: null,
  lang: null,
  ...extra,
})

describe("числа строки аккаунта", () => {
  it("числа студии стоят выше чисел профиля", () => {
    const a = acc("farm", { profile: { followers: 10, posts: { count: 26 } } })
    const counters: StudioCountersMap = { farm: { followers: 1200, posts: 19 } }
    expect(rowNumbers(a, counters)).toEqual({ followers: 1200, posts: 19, visitors: null })
  })

  it("чего студия не собрала — берётся из профиля", () => {
    const a = acc("farm", { profile: { followers: 10, posts: { count: 26 } } })
    expect(rowNumbers(a, { farm: { unread_visitors: 3 } })).toEqual({
      followers: 10,
      posts: 26,
      visitors: 3,
    })
  })

  it("без студии всё как было: числа из профиля", () => {
    const a = acc("farm", { profile: { followers: 10, posts: { count: 26 } } })
    expect(rowNumbers(a)).toEqual({ followers: 10, posts: 26, visitors: null })
    expect(rowNumbers(a, {})).toEqual({ followers: 10, posts: 26, visitors: null })
  })

  it("профиля нет — числа есть", () => {
    const a = acc("fresh")
    expect(rowNumbers(a, { fresh: { followers: 5, posts: 0, unread_visitors: 1 } })).toEqual({
      followers: 5,
      posts: 0,
      visitors: 1,
    })
  })

  it("ноль не считается «неизвестно» и профилем не подменяется", () => {
    const a = acc("farm", { profile: { followers: 900 } })
    expect(rowNumbers(a, { farm: { followers: 0 } }).followers).toBe(0)
  })

  it("неизвестное остаётся неизвестным", () => {
    expect(rowNumbers(acc("empty"), { empty: {} })).toEqual({
      followers: null,
      posts: null,
      visitors: null,
    })
  })
})
