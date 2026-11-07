import { describe, expect, it } from "vitest"

import type { Account } from "@/api/types"

import {
  ACCOUNT_ACTIONS,
  actionContext,
  ROW_ACTIONS,
  SELECTION_ACTIONS,
  visibleActions,
  type AccountActionContext,
  type AccountActionKey,
} from "./actions"
import { ACCOUNT_ACTION, COPY_LABEL } from "./labels"

/* Пункты у трёх входов (меню строки, контекстное меню, панель над выделением)
   берутся из одного списка, и разойтись им негде. Здесь проверяем то, за чем
   человек идёт в меню: какие пункты он увидит и какие из них живые. */

function acc(username: string, has_session = true): Account {
  return {
    username,
    has_session,
    has_totp: false,
    has_email: false,
    avatar: null,
    profile: null,
    region: null,
    lang: null,
  }
}

const row = (
  account: Account,
  flags: { locked?: boolean; busy?: boolean } = {}
) => actionContext([account], flags)

const selection = (
  accounts: Account[],
  flags: { locked?: boolean; busy?: boolean } = {}
) => actionContext(accounts, flags)

/** Состав входа по порядку списка. */
const keys = <K extends AccountActionKey>(
  list: readonly K[],
  ctx: AccountActionContext
) => visibleActions(list, ctx).map((a) => a.key)

/** Пункт входа — им же проверяется подпись и доступность. */
const at = <K extends AccountActionKey>(
  list: readonly K[],
  ctx: AccountActionContext,
  key: K
) => {
  const found = visibleActions(list, ctx).find((a) => a.key === key)
  if (!found) throw new Error(`пункта ${key} нет в этом входе`)
  return found
}

describe("пункты аккаунта", () => {
  it("у каждого ключа ровно один пункт, и входы берут их оттуда же", () => {
    const all = ACCOUNT_ACTIONS.map((a) => a.key)
    expect(new Set(all).size).toBe(all.length)
    // оба входа ссылаются на те же ключи, и чужих среди них нет
    for (const key of [...ROW_ACTIONS, ...SELECTION_ACTIONS])
      expect(all).toContain(key)
  })

  it("подписи берутся из общих текстов, а не заводятся заново", () => {
    const one = row(acc("one"))
    const many = selection([acc("one"), acc("two")])
    expect(at(ROW_ACTIONS, one, "publish").label(one)).toBe(
      ACCOUNT_ACTION.publish
    )
    expect(at(ROW_ACTIONS, one, "copy").label(one)).toBe(COPY_LABEL.one)
    expect(at(SELECTION_ACTIONS, many, "copy").label(many)).toBe(
      COPY_LABEL.many
    )
  })

  it("строка: без входа чистить нечего, входить она зовёт кнопкой, а не пунктом", () => {
    expect(keys(ROW_ACTIONS, row(acc("nologin", false)))).toEqual([
      "publish",
      "refresh",
      "open",
      "copy",
      "edit",
      "disable",
      "remove",
    ])
    expect(keys(ROW_ACTIONS, row(acc("in")))).toEqual([
      "publish",
      "refresh",
      "open",
      "copy",
      "edit",
      "purge",
      "clearSession",
      "logout",
      "disable",
      "remove",
    ])
  })

  it("выделение: вход — только когда ему есть куда идти, открывать профиль тут нечего", () => {
    expect(keys(SELECTION_ACTIONS, selection([acc("in")]))).toEqual([
      "publish",
      "refresh",
      "copy",
      "purge",
      "clearSession",
      "logout",
      "disable",
      "remove",
    ])
    expect(
      keys(SELECTION_ACTIONS, selection([acc("in"), acc("nologin", false)]))
    ).toEqual([
      "publish",
      "refresh",
      "copy",
      "login",
      "purge",
      "clearSession",
      "logout",
      "disable",
      "remove",
    ])
  })

  it("публикация гасит всё, что меняет аккаунты, а прочитать профиль не мешает", () => {
    const ctx = selection([acc("in")], { locked: true })
    expect(at(SELECTION_ACTIONS, ctx, "publish").disabled(ctx)).toBe(true)
    expect(at(SELECTION_ACTIONS, ctx, "purge").disabled(ctx)).toBe(true)
    expect(at(SELECTION_ACTIONS, ctx, "clearSession").disabled(ctx)).toBe(true)
    expect(at(SELECTION_ACTIONS, ctx, "logout").disabled(ctx)).toBe(true)
    expect(at(SELECTION_ACTIONS, ctx, "remove").disabled(ctx)).toBe(true)
    // обновление профиля и копирование юзернейма аккаунты не трогают
    expect(at(SELECTION_ACTIONS, ctx, "refresh").disabled(ctx)).toBe(false)
    expect(at(SELECTION_ACTIONS, ctx, "copy").disabled(ctx)).toBe(false)
  })

  it("занятость строки гасит её же пункты, но не копирование и не обновление профиля", () => {
    const ctx = row(acc("in"), { busy: true })
    expect(at(ROW_ACTIONS, ctx, "publish").disabled(ctx)).toBe(true)
    expect(at(ROW_ACTIONS, ctx, "edit").disabled(ctx)).toBe(true)
    expect(at(ROW_ACTIONS, ctx, "purge").disabled(ctx)).toBe(true)
    expect(at(ROW_ACTIONS, ctx, "clearSession").disabled(ctx)).toBe(true)
    expect(at(ROW_ACTIONS, ctx, "logout").disabled(ctx)).toBe(true)
    expect(at(ROW_ACTIONS, ctx, "remove").disabled(ctx)).toBe(true)
    // юзернейм идёт в буфер, а не в TikTok: ждать окончания работы незачем
    expect(at(ROW_ACTIONS, ctx, "copy").disabled(ctx)).toBe(false)
    // профиль читается анонимно и никому не мешает — как и у головной кнопки
    // «Обновить», занятость аккаунта этому действию не помеха
    expect(at(ROW_ACTIONS, ctx, "refresh").disabled(ctx)).toBe(false)
  })

  it("удаление — единственный пункт, отделённый чертой и покрашенный в красный", () => {
    const marked = ACCOUNT_ACTIONS.filter(
      (a) => a.destructive || a.separatorBefore
    )
    expect(marked.map((a) => a.key)).toEqual(["remove"])
    expect(marked[0].destructive).toBe(true)
    expect(marked[0].separatorBefore).toBe(true)
  })
})
