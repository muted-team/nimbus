import { t } from "@/lib/i18n"
import { create } from "zustand"

import {
  PURGE_POLL_MS,
  deleteAccount,
  loadPurgeStatus,
  loginAccount,
  purgeAccount,
  refreshAccounts,
  refreshAccountsSoon,
} from "@/api/accounts"
import { api } from "@/api/client"
import type { PurgeResult } from "@/api/types"
import { notify } from "@/lib/notify"

import { ACC_TOAST, RUN_TOAST, RUN_VERB } from "./labels"

/* Прогон по очереди аккаунтов — войти, сбросить вход, очистить посты или удалить: сколько
   дорожек, сколько потоков задано настройкой программы. Состояние глобальное:
   уход с экрана прогон не останавливает, панель прогресса вернётся на место.
   Остановка — после текущего аккаунта; 409 на входе значит, что идёт
   публикация, тогда встаём целиком. */

export type RunKind = "login" | "clearSession" | "logout" | "purge" | "delete"

/* Больше дорожек, чем разрешает браузер, только вредит: к одному адресу он
   держит шесть соединений, одно занято живым потоком событий. Лишние входы
   стояли бы в очереди, успевали упереться в свой таймаут и считались бы
   неудачными, хотя сервер их выполняет; заодно за ними вставали опрос списка и
   сохранение настроек. Сервер публикует в свои потоки и без нас. */
export const MAX_LANES = 4

export interface AccountsRun {
  kind: RunKind
  total: number
  /** завершённые: успешные и неудачные */
  done: number
  ok: number
  /** аккаунты в работе прямо сейчас */
  current: string[]
  stopping: boolean
}

interface RunStore {
  run: AccountsRun | null
  /** остановка запрошена: прогон встанет, доработав текущие аккаунты */
  stopping: boolean
  requestStop: () => void
}

export const useAccountsRun = create<RunStore>((set) => ({
  run: null,
  stopping: false,
  requestStop: () =>
    set((s) => ({
      stopping: true,
      run: s.run ? { ...s.run, stopping: true } : null,
    })),
}))

/** Чистки идут на сервере фоном: ждём, пока username исчезнет из списка
    текущих, и возвращаем её итог — по нему и считается «очищено». */
async function waitPurge(username: string): Promise<PurgeResult | undefined> {
  for (;;) {
    const st = await loadPurgeStatus()
    if (!st.current.includes(username)) return st.results?.[username]
    await new Promise((r) => setTimeout(r, PURGE_POLL_MS))
  }
}

/** Удалить только локально сохранённую авторизацию. Запросов в TikTok нет. */
const clearAccountSession = (username: string, newDevice = false) =>
  api.post<{ ok: boolean; username: string; had_session: boolean }>(
    "api/accounts/clear-session",
    { username, new_device: newDevice }
  )

/** Настоящий выход: гасит сессию у TikTok, при подтверждении сам чистит и
    локальный файл (main.py/_api_accounts_logout). confirmed=false — TikTok
    выход не подтвердил, локальная сессия могла остаться нетронутой. */
const logoutAccount = (username: string, newDevice = false) =>
  api.post<{
    ok: boolean
    username: string
    confirmed: boolean
    had_session: boolean
    error?: string | null
  }>("api/accounts/logout", { username, new_device: newDevice })

/* Живой прогон: очередь и счётчики. Держим рядом со стором, а не в нём, чтобы к
   идущему прогону можно было докинуть аккаунты — нажатие «Войти» на соседней
   строке не должно упираться в «подождите, идёт другой вход». */
let live: {
  kind: RunKind
  queue: string[]
  add: (names: string[]) => void
} | null = null

export interface RunOptions {
  /** только для kind === "delete": перед удалением попробовать настоящий
      выход у TikTok. Сбой выхода удаление не отменяет — это подстраховка,
      а не условие; в отчёт попадает только исход самого удаления. */
  logoutFirst?: boolean
  /** «Забыть», «Выйти», «Удалить»: стереть и компьютер аккаунта — следующий
      вход будет с новым. Без неё компьютер сохраняется. */
  newDevice?: boolean
}

export function startRun(
  kind: RunKind,
  queue: string[],
  threads = 1,
  opts: RunOptions = {}
) {
  queue = [...new Set(queue)]
  if (!queue.length) return
  if (live) {
    // тот же вид работы — просто дописываем в очередь; другой — это уже
    // другой прогресс, второй одновременно показывать негде
    if (live.kind === kind) live.add(queue)
    else notify.warn(RUN_TOAST.otherRunning(live.kind))
    return
  }

  // stopping живёт в сторе, а не здесь: объект прогона пересобирается на
  // каждом commit, и флаг, положенный в него, затирался бы при первом же
  // завершённом аккаунте — «Остановить» перестала бы работать
  const state: Omit<AccountsRun, "stopping"> & {
    failed: { username: string; reason: string }[]
    banned: { username: string; reason: string }[]
    campStopped: boolean
  } = {
    kind,
    total: queue.length,
    done: 0,
    ok: 0,
    current: [],
    failed: [],
    banned: [],
    campStopped: false,
  }
  const commit = () =>
    useAccountsRun.setState({
      run: {
        ...state,
        stopping: useAccountsRun.getState().stopping,
        current: [...state.current],
      },
    })
  useAccountsRun.setState({ stopping: false })
  commit()

  const fail = (username: string, reason: string) => {
    state.failed.push({ username, reason: reason || t("причина неизвестна") })
  }

  /** отработанные: докинутый второй раз аккаунт в очередь не встаёт */
  const done = new Set<string>()

  async function lane() {
    for (;;) {
      const run = useAccountsRun.getState().run
      if (!run || run.stopping || state.campStopped) return
      const username = queue.shift()
      if (!username) return
      state.current.push(username)
      commit()
      try {
        if (kind === "login") {
          const res = await loginAccount(username)
          if (res.ok) state.ok += 1
          else if (res.banned)
            state.banned.push({
              username,
              reason: res.reason || t("аккаунта нет"),
            })
          else fail(username, res.reason || "")
        } else if (kind === "clearSession") {
          await clearAccountSession(username, opts.newDevice)
          state.ok += 1
        } else if (kind === "logout") {
          const res = await logoutAccount(username, opts.newDevice)
          if (res.confirmed && !res.error) state.ok += 1
          else fail(username, res.error || t("TikTok не подтвердил выход"))
        } else if (kind === "purge") {
          await purgeAccount(username)
          // чистка фоновая: шаг ждёт её конца и считает удачей только то, что
          // сервер действительно снёс, а не саму принятую задачу
          const res = await waitPurge(username)
          if (!res) fail(username, t("результат очистки не получен"))
          else if (res.error) fail(username, res.error)
          else state.ok += 1
        } else {
          if (opts.logoutFirst) {
            // подстраховка, не условие удаления: сеть шатается, прокси может
            // не найтись — аккаунт всё равно должен уйти по прямому запросу
            await logoutAccount(username, opts.newDevice).catch(() => undefined)
          }
          await deleteAccount(username, opts.newDevice)
          state.ok += 1
        }
      } catch (error) {
        const status = (error as { status?: number }).status
        if (kind === "login" && status === 409) {
          state.campStopped = true
        } else {
          fail(username, error instanceof Error ? error.message : String(error))
        }
      }
      state.done += 1
      done.add(username)
      state.current = state.current.filter((u) => u !== username)
      commit()
      refreshAccountsSoon()
    }
  }

  const maxLanes = Math.max(1, Math.min(threads, MAX_LANES))
  let active = 0
  /** Поднять дорожки под очередь, но не больше предела. */
  function spawn() {
    const want = Math.min(maxLanes - active, queue.length)
    for (let i = 0; i < want; i++) {
      active += 1
      void lane().finally(() => {
        active -= 1
        if (!active) finish()
      })
    }
  }

  live = {
    kind,
    queue,
    add: (names) => {
      const fresh = names.filter(
        (u) => !queue.includes(u) && !done.has(u) && !state.current.includes(u)
      )
      if (!fresh.length) return
      queue.push(...fresh)
      state.total += fresh.length
      commit()
      spawn() // дорожки могли уже разойтись — поднимаем заново
    },
  }
  spawn()

  function finish() {
    const stopped = useAccountsRun.getState().stopping
    live = null
    useAccountsRun.setState({ run: null, stopping: false })
    void refreshAccounts()
    if (state.campStopped) {
      notify.warn(ACC_TOAST.campLogin)
      return
    }
    const lines = [
      RUN_TOAST.done(kind, stopped, state.ok, state.total),
      ...(state.banned.length
        ? [RUN_TOAST.bannedLine(state.banned.map((b) => b.username))]
        : []),
      ...state.failed.map((f) => RUN_TOAST.failLine(f.username, f.reason)),
    ]
    const bad = state.failed.length + state.banned.length
    const [head, ...rest] = lines
    if (!bad) notify.ok(head)
    else if (!state.ok) notify.error(head, undefined, { lines: rest })
    else notify.warn(head, { lines: rest })
  }
}

/** Короткая строка прогресса для панели: «Вхожу: 3/10 (user)…». */
export function runProgressText(run: AccountsRun): string {
  const inWork =
    run.current.length === 1
      ? run.current[0]
      : run.current.length
        ? t("разом {0}", [run.current.length])
        : ""
  return `${RUN_VERB[run.kind]}: ${run.done}/${run.total}${inWork ? ` (${inWork})` : ""}…`
}
