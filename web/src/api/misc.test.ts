import { QueryObserver } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { refreshSlotInfo } from "./misc"
import { keys, queryClient } from "./query-client"

/* Обновление чисел после загрузки файла: ключ у каждого набора папок свой, и
   помечать устаревшими наборы, которых на экране нет, незачем. */

const empty = async () => new Map()

beforeEach(() => queryClient.clear())
afterEach(() => queryClient.clear())

it("перепрашивает только показанный набор папок", async () => {
  const shownFn = vi.fn(empty)
  const otherFn = vi.fn(empty)
  await queryClient.fetchQuery({ queryKey: keys.slots(["a", "b"]), queryFn: shownFn })
  await queryClient.fetchQuery({ queryKey: keys.slots(["c"]), queryFn: otherFn })
  // набор ["a", "b"] показан на экране, ["c"] лежит в кэше без экрана
  const shown = new QueryObserver(queryClient, { queryKey: keys.slots(["a", "b"]), queryFn: shownFn })
  const unsubscribe = shown.subscribe(() => {})
  shownFn.mockClear()
  otherFn.mockClear()

  await refreshSlotInfo()

  expect(shownFn).toHaveBeenCalledTimes(1)
  expect(otherFn).toHaveBeenCalledTimes(0)
  expect(queryClient.getQueryState(keys.slots(["c"]))?.isInvalidated).toBe(false)
  unsubscribe()
  shown.destroy()
})

it("показанных наборов нет — обновляет все", async () => {
  queryClient.setQueryData(keys.slots(["a"]), new Map())
  queryClient.setQueryData(keys.slots(["b"]), new Map())

  await refreshSlotInfo()

  expect(queryClient.getQueryState(keys.slots(["a"]))?.isInvalidated).toBe(true)
  expect(queryClient.getQueryState(keys.slots(["b"]))?.isInvalidated).toBe(true)
})
