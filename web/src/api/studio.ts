import { useQuery } from "@tanstack/react-query"

import { ApiError, api } from "./client"
import { keys } from "./query-client"
import type { StudioCountersMap } from "./types"

/* Числа аккаунта: сколько постов, подписчиков и непрочитанных посетителей.
   Считает сам аккаунт по своим кукам — одним запросом, без подписи и без
   анонимного сбора профиля с прокси (modules/studio.py:counters).

   Идут отдельно от списка аккаунтов и меняются медленнее него, поэтому и
   опрашиваются реже. Пока сервер их не собрал, экран показывает то, что уже
   есть в профиле, — прочерков из-за этого не прибавляется. */

export const STUDIO_POLL_MS = 60_000

/** Числа студии по всем аккаунтам с сохранённым входом. */
export function useStudioCounters(enabled: boolean) {
  return useQuery({
    queryKey: keys.studioCounters,
    queryFn: async () => {
      const res = await api.get<{ counters: StudioCountersMap }>("api/studio/counters")
      return res.counters ?? {}
    },
    enabled,
    // такой ручки сервер может не знать — тогда стучимся один раз и молчим
    refetchInterval: (query) =>
      query.state.error instanceof ApiError && query.state.error.status === 404
        ? false
        : STUDIO_POLL_MS,
    // на каждом опросе числа остаются на месте: прочерк вместо них мигал бы
    placeholderData: (prev) => prev,
  })
}
