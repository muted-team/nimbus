import { QueryClient } from "@tanstack/react-query"

import { ApiError } from "./client"

/* Один клиент на приложение: живой поток (stream.ts) пишет в его кэш те же
   данные, что приходят опросом, — экраны не знают, откуда пришло обновление. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      // сервер локальный: повтор нужен только на обрыв связи, а не на 4xx
      retry: (failures, error) =>
        failures < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
})

const SLOTS_ROOT = "slots" as const

export const keys = {
  accounts: ["accounts"] as const,
  avatars: ["avatars"] as const,
  // числа студии живут своей жизнью: обновление списка их не перепрашивает
  studioCounters: ["studio", "counters"] as const,
  profilesRefresh: ["profiles", "refresh"] as const,
  // не вложен в accounts: обновление списка не должно заодно перезапрашивать
  // состояние чисток
  purge: ["purge"] as const,
  proxies: ["proxies"] as const,
  campaignStatus: ["campaign", "status"] as const,
  campaignForm: ["campaign", "form"] as const,
  settings: ["settings"] as const,
  serverCheck: ["server-check"] as const,
  license: ["license"] as const,
  licenseHistory: ["license", "history"] as const,
  uniq: ["uniq"] as const,
  // корень ключей наборов папок: по нему ищут все наборы сразу (refreshSlotInfo)
  slotsRoot: [SLOTS_ROOT] as const,
  slots: (folders: string[]) => [SLOTS_ROOT, folders] as const,
  changelog: ["changelog"] as const,
  media: ["media"] as const,
  mediaFiles: (name: string) => ["media", "files", name] as const,
}
