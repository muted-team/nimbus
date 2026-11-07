import { useInfiniteQuery, useQuery } from "@tanstack/react-query"

import { api } from "./client"
import { keys, queryClient } from "./query-client"
import type { LicenseHistory, LicenseInfo } from "./types"

/* Ключ к нашему серверу, баланс и история списаний. Сам сервер программа
   спрашивает у себя (main.py -> modules/remote.py): адрес сервера знает только
   бэкенд, интерфейс о нём не знает ничего. */

export function useLicense() {
  return useQuery({
    queryKey: keys.license,
    queryFn: () => api.get<LicenseInfo>("api/license"),
    // баланс меняется от работы — свежий при каждом заходе в раздел
    staleTime: 0,
    refetchOnMount: "always",
  })
}

/** Проверить ключ у сервера и сохранить; пустой — удалить. */
export async function saveLicenseKey(key: string) {
  const res = await api.put<LicenseInfo>("api/license", { key })
  queryClient.setQueryData(keys.license, res)
  void queryClient.invalidateQueries({ queryKey: keys.licenseHistory })
  return res
}

const PAGE = 50

export function useLicenseHistory(enabled: boolean) {
  return useInfiniteQuery({
    queryKey: keys.licenseHistory,
    queryFn: ({ pageParam }) =>
      api.get<LicenseHistory>(
        `api/license/history?limit=${PAGE}` +
          (pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "")
      ),
    initialPageParam: "",
    getNextPageParam: (last) => last.next || undefined,
    enabled,
  })
}
