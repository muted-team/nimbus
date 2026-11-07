import { useQuery } from "@tanstack/react-query"

import { api } from "./client"
import { keys, queryClient } from "./query-client"
import type { ProxiesResponse, ProxyHealth, ProxyRotateResponse } from "./types"

/* Смена IP у прокси ждётся дольше остальных запросов: сервер дёргает ссылку
   провайдера и сам ждёт результата (modules/proxies.py). Слагаемые пути при
   настройках по умолчанию: пауза между сменами одной ссылки 30 с + проверка
   адреса «до» 15 с + до трёх попыток дёрнуть ссылку по 20 с с паузами 10 с
   (80 с) + выдержка после ссылки 3 с + проверка адреса «после» до четырёх раз
   по 15 с (66 с) — до ~200 с. Таймаут короче этого рвёт удачную, но медленную
   смену: на сервере IP уже сменился, а человек видит «сменить не удалось». */
const ROTATE_TIMEOUT = 240_000

export function useProxies() {
  return useQuery({
    queryKey: keys.proxies,
    queryFn: () => api.get<ProxiesResponse>("api/proxies"),
  })
}

/** Заменить список (текст по прокси на строку) и/или тумблер «использовать».
 *
 *  login, publish и off — НОМЕРА строк в присылаемом списке: какие годятся для
 *  входа, публикации и какие выключены. Номерами, а не адресами, потому что у пачки от
 *  одного провайдера адрес общий, а различаются строки только учётками —
 *  развести их по адресу нельзя. Список и отметки едут одним запросом и
 *  поэтому не могут разъехаться. Поля НЕТ в запросе — сервер эту отметку не
 *  трогает: правка одной строки шлёт весь список, и «нет поля = пусто» снимало
 *  бы все отметки при каждом сохранении. */
export async function saveProxies(patch: {
  text?: string
  enabled?: boolean
  login?: number[]
  publish?: number[]
  off?: number[]
}) {
  const res = await api.put<ProxiesResponse>("api/proxies", patch)
  queryClient.setQueryData(keys.proxies, res)
  return res
}

/** Проверка всех прокси разом; ход по строкам приходит живым потоком. */
export async function checkProxies() {
  const res = await api.post<ProxiesResponse>("api/proxies/check", {}, { timeout: 120_000 })
  queryClient.setQueryData<ProxiesResponse>(keys.proxies, (data) =>
    data ? { ...data, health: res.health } : res
  )
  return res
}

/** Отметки проверки из живого потока. */
export function applyProxyHealth(health: ProxyHealth[]) {
  queryClient.setQueryData<ProxiesResponse>(keys.proxies, (data) =>
    data ? { ...data, health } : data
  )
}

/** Сменить IP у строки списка. Ждёт провайдера до нескольких минут: смена идёт
    на сервере, и обрывать её на полдороге значит показать неудачу вместо итога. */
export async function rotateProxy(index: number) {
  const res = await api.post<ProxyRotateResponse>("api/proxies/rotate", { index },
    { timeout: ROTATE_TIMEOUT })
  // в кэш кладём снимок списка, а итог возвращаем вызывающему под тост
  const { ok, ip_before, ip_after, reason, ...snapshot } = res
  queryClient.setQueryData(keys.proxies, snapshot)
  return { ok, ip_before, ip_after, reason }
}
