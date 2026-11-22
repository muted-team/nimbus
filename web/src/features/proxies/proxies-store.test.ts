import { beforeEach, describe, expect, it, vi } from "vitest"
import { keys, queryClient } from "@/api/query-client"
import type { ProxiesResponse } from "@/api/types"

import { indexesAfterRemoval, mutateProxies, proxiesTextToSave, useProxiesStore } from "./proxies-store"

beforeEach(() => {
  queryClient.clear()
  useProxiesStore.setState({ mutating: false })
})

/* T-201 (dev/_probe_proxy_wipe.py): открытие раздела не должно стирать
   список. Раньше пустой текст мог улететь сам — здесь единственная дверь для
   пустоты — явное действие человека «удалить последнюю строку». */

describe("что уйдёт на сервер", () => {
  it("пустой список без явного действия — не уходит вовсе", () => {
    expect(proxiesTextToSave([], false)).toBeNull()
  })

  it("пустой список по «удалить последнюю строку» — уходит пустой строкой", () => {
    expect(proxiesTextToSave([], true)).toBe("")
  })

  it("непустой список уходит всегда, независимо от allowEmpty", () => {
    expect(proxiesTextToSave(["a", "b"], false)).toBe("a\nb")
    expect(proxiesTextToSave(["a", "b"], true)).toBe("a\nb")
  })
})

describe("отметки после удаления строки", () => {
  it("снимает отметку удалённой строки и сдвигает только правые", () => {
    expect(indexesAfterRemoval([0, 2, 4], 2)).toEqual([0, 3])
  })

  it("не меняет индексы слева от удалённой строки", () => {
    expect(indexesAfterRemoval([0, 1], 3)).toEqual([0, 1])
  })
})

describe("shared proxy mutation guard", () => {
  it("refuses another writer synchronously until the first response settles", async () => {
    let finish!: (value: string) => void
    const first = mutateProxies(["fixture"], () => new Promise<string>((resolve) => { finish = resolve }))
    const other = vi.fn(async () => "not applied")
    expect(useProxiesStore.getState().mutating).toBe(true)
    expect(await mutateProxies(["fixture"], other)).toBeNull()
    expect(other).not.toHaveBeenCalled()
    finish("applied")
    expect(await first).toBe("applied")
    expect(useProxiesStore.getState().mutating).toBe(false)
    expect(await mutateProxies(["fixture"], other)).toBe("not applied")
  })

  it("refuses an old whole-list or index snapshot after deletion has completed", async () => {
    queryClient.setQueryData<ProxiesResponse>(keys.proxies, { proxies: ["b", "c"], health: [], enabled: true, rotating: 0, errors: [] })
    const write = vi.fn(async () => true)
    expect(await mutateProxies(["a", "b", "c"], write)).toBeNull()
    expect(write).not.toHaveBeenCalled()
    expect(await mutateProxies(["b", "c"], write)).toBe(true)
  })

  it("releases the guard on network or validation failure", async () => {
    const error = new Error("synthetic write refused")
    await expect(mutateProxies([], async () => { throw error })).rejects.toBe(error)
    expect(useProxiesStore.getState().mutating).toBe(false)
    expect(await mutateProxies([], async () => true)).toBe(true)
  })
})
