import { useQuery } from "@tanstack/react-query"
import { useLocation } from "wouter"

import { sectionPath } from "@/app/sections"

import { api, LONG_TIMEOUT } from "./client"
import { keys, queryClient } from "./query-client"
import type {
  Account,
  AccountPatch,
  AccountSecrets,
  AccountsResponse,
  AvatarsResponse,
  BulkAddResponse,
  LoginResponse,
  Profile,
  ProfilesStatus,
  PurgeStatus,
} from "./types"

const ACCOUNTS_POLL_MS = 15_000

/* Когда живой поток в последний раз прислал строку аккаунта. Список,
   запрошенный раньше, эту строку не затирает: поток свежее, а следующее
   изменение он всё равно пришлёт сам. */
const rowsAt = new Map<string, number>()

function avatarStamps(accounts: Account[]) {
  return accounts.map((a) => `${a.username}:${a.avatar ?? ""}`).join("|")
}

async function fetchAccounts(): Promise<AccountsResponse> {
  const sentAt = Date.now()
  const prev = queryClient.getQueryData<AccountsResponse>(keys.accounts)
  const res = await api.get<AccountsResponse>("api/accounts")
  const old = new Map(prev?.accounts.map((a) => [a.username, a]))
  const accounts = res.accounts.map((a) => {
    const cached = old.get(a.username)
    if (cached && (rowsAt.get(a.username) ?? 0) > sentAt) {
      return { ...a, profile: cached.profile, avatar: cached.avatar }
    }
    return a
  })
  // картинки тяжёлые и в опрос списка не входят: перечитываем их, только
  // когда поменялся набор отметок (новый вход, удаление аккаунта)
  if (!prev || avatarStamps(prev.accounts) !== avatarStamps(accounts)) {
    void queryClient.invalidateQueries({ queryKey: keys.avatars })
  }
  return { accounts, banned: res.banned ?? [] }
}

/** Список аккаунтов. Опрос раз в 15 с идёт, только пока открыт экран аккаунтов:
    на остальных список обновляют события живого потока и refreshAccounts. */
export function useAccounts() {
  const [location] = useLocation()
  return useQuery({
    queryKey: keys.accounts,
    queryFn: fetchAccounts,
    refetchInterval: location === sectionPath("accounts") ? ACCOUNTS_POLL_MS : false,
  })
}

export function useAvatars() {
  return useQuery({
    queryKey: keys.avatars,
    queryFn: async () => (await api.get<AvatarsResponse>("api/avatars")).avatars,
    staleTime: Infinity,
  })
}

export const refreshAccounts = () => queryClient.invalidateQueries({ queryKey: keys.accounts })

/* Прогон по десяткам аккаунтов заканчивает их пачками, и каждый конец звал
   перечитать весь список: сервер получал десяток одинаковых запросов разом.
   Придерживаем: один запрос сразу, следующий — не раньше чем через паузу. */
const REFRESH_GAP_MS = 1_500
let refreshAt = 0
let refreshTimer: ReturnType<typeof setTimeout> | null = null

export function refreshAccountsSoon() {
  if (refreshTimer) return
  const wait = Math.max(0, refreshAt + REFRESH_GAP_MS - Date.now())
  if (!wait) {
    refreshAt = Date.now()
    void refreshAccounts()
    return
  }
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    refreshAt = Date.now()
    void refreshAccounts()
  }, wait)
}

/** Свежие строки из живого потока: профиль и аватарка — в момент записи в базу. */
export function applyProfileRows(
  profiles: Record<string, Profile> | undefined,
  avatars: Record<string, { at: number; data: string }> | undefined
) {
  const now = Date.now()
  const faces = avatars ?? {}
  queryClient.setQueryData<AccountsResponse>(keys.accounts, (data) => {
    if (!data) return data
    return {
      ...data,
      accounts: data.accounts.map((a) => {
        const profile = profiles?.[a.username]
        const face = faces[a.username]
        if (!profile && !face) return a
        rowsAt.set(a.username, now)
        return {
          ...a,
          profile: profile ?? a.profile,
          avatar: face ? face.at : a.avatar,
        }
      }),
    }
  })
  const names = Object.keys(faces)
  if (names.length) {
    queryClient.setQueryData<Record<string, string>>(keys.avatars, (map) => {
      const next = { ...map }
      for (const u of names) next[u] = faces[u].data
      return next
    })
  }
}

export const addAccountsBulk = (text: string) =>
  api.post<BulkAddResponse>("api/accounts/bulk", { text }, { timeout: LONG_TIMEOUT })

/** Ручная правка одного аккаунта: пароль сменился, логин определился неверно
    и т.п. patch несёт только изменённые поля — остальные у аккаунта не
    трогаются. Ответ — свежая строка аккаунта (без секретов), кладём её сразу
    в кэш списка, не дожидаясь опроса. */
export async function updateAccount(username: string, patch: AccountPatch) {
  const account = await api.post<Account>("api/accounts/update", { username, patch })
  queryClient.setQueryData<AccountsResponse>(keys.accounts, (data) => {
    if (!data) return data
    return {
      ...data,
      accounts: data.accounts.map((a) => (a.username === username ? account : a)),
    }
  })
  return account
}

/** Пароль и источник кода одного аккаунта открытым текстом — только для
    формы ручной правки, не кладём в общий кэш списка (там секретов не
    место). */
export const fetchAccountSecrets = (username: string) =>
  api.get<AccountSecrets>(`api/accounts/secrets?username=${encodeURIComponent(username)}`)

/** Секреты одного аккаунта — только для формы ручной правки, staleTime: 0
    (не кэшируем между открытиями панели: секрет мог смениться прогоном
    входа с другого места) и без окна в общий кэш keys.accounts. */
export function useAccountSecrets(username: string) {
  return useQuery({
    queryKey: ["accounts", "secrets", username] as const,
    queryFn: () => fetchAccountSecrets(username),
    staleTime: 0,
    gcTime: 0,
  })
}

export const loginAccount = (username: string) =>
  api.post<LoginResponse>("api/login", { username }, { timeout: LONG_TIMEOUT })

/** newDevice — стереть и компьютер аккаунта: добавленный снова войдёт с новым. */
export const deleteAccount = (username: string, newDevice = false) =>
  api.post<{ ok: boolean }>("api/accounts/delete", {
    username,
    new_device: newDevice,
  })

export const restoreAccount = (username: string) =>
  api.post<{ ok: boolean }>("api/accounts/restore", { username })

/** Вручную отключить аккаунт(ы): уходят в отключённые с живой сессией,
    "Вернуть" отдаст их обратно. */
export const disableAccounts = (usernames: string[]) =>
  api.post<{ ok: boolean; disabled: string[]; missing: string[] }>(
    "api/accounts/disable",
    { usernames },
  )

/** Очистка постов идёт на сервере фоном: ответ приходит сразу. count -1 — все. */
export async function purgeAccount(username: string, count = -1) {
  const res = await api.post<{ ok: boolean }>("api/accounts/purge", { username, count })
  // сама чистка только началась: будим опрос её хода, иначе спиннер на строке
  // появился бы лишь со следующим обновлением списка
  void queryClient.invalidateQueries({ queryKey: keys.purge })
  return res
}

export const PURGE_POLL_MS = 1_500

const fetchPurgeStatus = () => api.get<PurgeStatus>("api/accounts/purge")

/** Свежий ход чисток вне компонента (ожидание конца прогона): тот же запрос и
    тот же кэш, что у usePurgeStatus, — второго опроса адреса нет. */
export const loadPurgeStatus = () =>
  queryClient.fetchQuery({ queryKey: keys.purge, queryFn: fetchPurgeStatus, staleTime: 0 })

/** Какие чистки идут прямо сейчас; опрос — пока хоть одна идёт. */
export function usePurgeStatus() {
  return useQuery({
    queryKey: keys.purge,
    queryFn: fetchPurgeStatus,
    refetchInterval: (q) => (q.state.data?.current.length ? PURGE_POLL_MS : false),
  })
}

/* ── фоновое обновление профилей ─────────────────────────────────────── */

export function useProfilesRefresh() {
  return useQuery({
    queryKey: keys.profilesRefresh,
    queryFn: () => api.get<ProfilesStatus>("api/profiles/refresh"),
    staleTime: Infinity,
  })
}

/** Снимок хода: не новее известного (seq не больше) не применяем. */
export function setProfilesStatus(next: ProfilesStatus) {
  const prev = queryClient.getQueryData<ProfilesStatus>(keys.profilesRefresh)
  if (prev && prev.seq >= next.seq) return prev
  queryClient.setQueryData(keys.profilesRefresh, next)
  return next
}

/** Запуск обновления профилей: всех или только usernames. */
export async function startProfilesRefresh(usernames?: string[]) {
  const status = await api.post<ProfilesStatus>(
    "api/profiles/refresh",
    usernames ? { usernames } : {}
  )
  return setProfilesStatus(status)
}
