import { describe, expect, it } from "vitest"

import type { Account } from "@/api/types"

import {
  defaultDir,
  filterAccounts,
  filterCounts,
  inShadow,
  isReady,
  searchByName,
  sortAccounts,
} from "./filter"

/* Срез списка — это обещание пользователю: в «Готовы» не должно быть ничего,
   что нельзя пустить в работу, а отключённые не должны просачиваться в общий
   список. Порядок строк проверяем на «неизвестно» — такие всегда внизу. */

function acc(username: string, extra: Partial<Account> = {}): Account {
  return {
    username,
    has_session: true,
    has_totp: false,
    has_email: false,
    avatar: null,
    profile: null,
    region: null,
    lang: null,
    ...extra,
  }
}

const withPosts = (username: string, shadow: number | null, has_session = true) =>
  acc(username, { has_session, profile: { posts: { count: 10, shadow } } })

describe("срезы списка", () => {
  const list = [
    acc("clean"),
    acc("nologin", { has_session: false }),
    withPosts("shadowed", 3),
    withPosts("checked", 0),
    withPosts("darknologin", 2, false),
  ]

  it("«Готовы» — со входом и без теней", () => {
    expect(filterAccounts(list, "ready").map((a) => a.username)).toEqual(["clean", "checked"])
  })

  it("«Все» — весь живой список, забаненных здесь нет", () => {
    expect(filterAccounts(list, "all")).toHaveLength(5)
  })

  it("«Без входа» и «В тени» пересекаются, и это нормально", () => {
    expect(filterAccounts(list, "nologin").map((a) => a.username)).toEqual([
      "nologin",
      "darknologin",
    ])
    expect(filterAccounts(list, "shadow").map((a) => a.username)).toEqual([
      "shadowed",
      "darknologin",
    ])
  })

  it("«Отключены» живёт своим списком — обычные аккаунты в него не попадают", () => {
    expect(filterAccounts(list, "banned")).toEqual([])
  })

  it("проверенные посты без теней — это не тень", () => {
    expect(inShadow(withPosts("checked", 0))).toBe(false)
    expect(isReady(withPosts("checked", 0))).toBe(true)
    expect(isReady(withPosts("shadowed", 1))).toBe(false)
  })

  it("счётчики чипов считаются по всему списку, а не по открытому срезу", () => {
    const counts = filterCounts(list, [{ username: "gone" }])
    expect(counts).toEqual({ ready: 2, all: 5, nologin: 2, shadow: 2, banned: 1 })
  })

  it("поиск по логину не смотрит на регистр", () => {
    expect(searchByName(list, "NOLOG").map((a) => a.username)).toEqual(["nologin", "darknologin"])
    expect(searchByName(list, "  ")).toHaveLength(5)
  })

  it("поиск задевает и страну аккаунта", () => {
    const withRegions = [acc("us1", { region: "US" }), acc("de1", { region: "DE" }), acc("noregion")]
    expect(searchByName(withRegions, "US").map((a) => a.username)).toEqual(["us1"])
    // без региона запрос по коду страны не совпадает — это не ошибка, а «не знаем»
    expect(searchByName(withRegions, "de").map((a) => a.username)).toEqual(["de1"])
  })
})

describe("порядок строк", () => {
  const byName = (list: Account[]) => list.map((a) => a.username)

  it("логин и страна — по алфавиту, числа — от большего", () => {
    expect(defaultDir("name")).toBe("asc")
    expect(defaultDir("region")).toBe("asc")
    expect(defaultDir("followers")).toBe("desc")
  })

  it("сортировка не трогает исходный список", () => {
    const list = [acc("b"), acc("a")]
    sortAccounts(list, "name", "asc")
    expect(byName(list)).toEqual(["b", "a"])
  })

  it("«неизвестно» всегда внизу — и по возрастанию, и по убыванию", () => {
    const list = [
      acc("noprofile"),
      acc("small", { profile: { followers: 10 } }),
      acc("big", { profile: { followers: 900 } }),
    ]
    expect(byName(sortAccounts(list, "followers", "desc"))).toEqual(["big", "small", "noprofile"])
    expect(byName(sortAccounts(list, "followers", "asc"))).toEqual(["small", "big", "noprofile"])
  })

  it("равные числа разбираются по логину", () => {
    const list = [
      acc("zed", { profile: { followers: 5 } }),
      acc("amy", { profile: { followers: 5 } }),
    ]
    expect(byName(sortAccounts(list, "followers", "desc"))).toEqual(["amy", "zed"])
  })

  it("ноль — это значение, а не «неизвестно»", () => {
    const list = [acc("none"), withPosts("zero", 0), withPosts("two", 2)]
    expect(byName(sortAccounts(list, "shadow", "desc"))).toEqual(["two", "zero", "none"])
  })

  it("страна — по алфавиту, «неизвестно» всегда внизу", () => {
    const list = [acc("noregion"), acc("de", { region: "DE" }), acc("us", { region: "US" })]
    expect(byName(sortAccounts(list, "region", "asc"))).toEqual(["de", "us", "noregion"])
    expect(byName(sortAccounts(list, "region", "desc"))).toEqual(["us", "de", "noregion"])
  })

  it("одна страна на несколько аккаунтов — дальше решает логин", () => {
    const list = [acc("zed", { region: "US" }), acc("amy", { region: "US" })]
    expect(byName(sortAccounts(list, "region", "asc"))).toEqual(["amy", "zed"])
  })

  it("порядок идёт по тем же числам, что стоят в колонке: студия выше профиля", () => {
    const list = [
      acc("byprofile", { profile: { followers: 900 } }),
      acc("bystudio", { profile: { followers: 10 } }),
    ]
    const counters = { bystudio: { followers: 1200 } }
    expect(byName(sortAccounts(list, "followers", "desc", counters))).toEqual([
      "bystudio",
      "byprofile",
    ])
    // без чисел студии порядок прежний — по профилю
    expect(byName(sortAccounts(list, "followers", "desc"))).toEqual(["byprofile", "bystudio"])
  })
})
