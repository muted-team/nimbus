import { t } from "@/lib/i18n"
import { create } from "zustand"

import {
  PURGE_POLL_MS,
  applyProfileRows,
  deleteAccount,
  loadPurgeStatus,
  loginAccount,
  purgeAccount,
  refreshAccounts,
  refreshAccountsSoon,
} from "@/api/accounts"
import { api, ApiError } from "@/api/client"
import {
  startRegistration,
  registrationStatus,
  type RegistrationInput,
  type RegistrationStatus,
} from "@/api/registration"
import { registrationPolling } from "./registration-view"
import type { PurgeResult } from "@/api/types"
import { notify } from "@/lib/notify"

import { ACC_TOAST, RUN_TOAST, RUN_VERB } from "./labels"

/* Прогон по очереди аккаунтов — войти, сбросить вход, очистить посты или удалить: сколько
   дорожек, сколько потоков задано настройкой программы. Состояние глобальное:
   уход с экрана прогон не останавливает, панель прогресса вернётся на место.
   Остановка — после текущего аккаунта; 409 на входе значит, что идёт
   публикация, тогда встаём целиком. */

export type RunKind =
  "register" | "login" | "clearSession" | "logout" | "purge" | "delete"

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
  registrationCurrent: RegistrationStatus | null
  registrationResults: RegistrationStatus[]
  registrationPollError: string | null
  setRegistrationResults: (results: RegistrationStatus[]) => void
  requestStop: () => void
}

export const useAccountsRun = create<RunStore>((set) => ({
  run: null,
  stopping: false,
  registrationCurrent: null,
  registrationResults: [],
  registrationPollError: null,
  setRegistrationResults: (registrationResults) => set({ registrationResults }),
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
  registration?: RegistrationInput
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
    if (live.kind === kind && kind !== "register") live.add(queue)
    else notify.warn(RUN_TOAST.otherRunning(live.kind))
    return
  }

  // stopping живёт в сторе, а не здесь: объект прогона пересобирается на
  // каждом commit, и флаг, положенный в него, затирался бы при первом же
  // завершённом аккаунте — «Остановить» перестала бы работать
  const state: Omit<AccountsRun, "stopping"> & {
    failed: { username: string; reason: string }[]
    banned: { username: string; reason: string }[]
    warnings: { username: string; reason: string }[]
    campStopped: boolean
  } = {
    kind,
    total: queue.length,
    done: 0,
    ok: 0,
    current: [],
    failed: [],
    banned: [],
    warnings: [],
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
  useAccountsRun.setState({
    stopping: false,
    ...(kind === "register"
      ? {
          registrationResults: [],
          registrationCurrent: null,
          registrationPollError: null,
        }
      : {}),
  })
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
        if (kind === "register") {
          if (!opts.registration)
            throw new Error(t("Не заданы параметры регистрации"))
          let result = await startRegistration(opts.registration)
          useAccountsRun.setState({ registrationCurrent: result })
          const jobId = result.job_id
          const scope = result.scope
          while (registrationPolling(result)) {
            await new Promise((resolve) => setTimeout(resolve, 2_000))
            let next: RegistrationStatus
            try {
              next = await registrationStatus()
            } catch (error) {
              if (
                error instanceof ApiError &&
                error.status >= 400 &&
                error.status < 500 &&
                error.status !== 408
              )
                throw error
              // The admitted job may still be running. Stop the remaining queue,
              // but recover its status with GET only; never repeat admission.
              useAccountsRun.getState().requestStop()
              useAccountsRun.setState({
                registrationPollError:
                  t(
                    "Не удалось проверить задание. Проверка продолжится; создание аккаунта не повторяется"
                  ) + (error instanceof Error ? `: ${error.message}` : ""),
              })
              continue
            }
            useAccountsRun.setState({ registrationPollError: null })
            if (next.job_id !== jobId || (scope && next.scope !== scope))
              throw new Error(
                t("Сервер или задание изменились. Очередь остановлена")
              )
            result = next
            useAccountsRun.setState({ registrationCurrent: result })
          }
          useAccountsRun.setState((store) => ({
            registrationResults: [...store.registrationResults, result],
          }))
          const badSelection = ["unknown", "blocked"].includes(
            result.username_selection?.status ?? ""
          )
          if (
            result.status === "complete" &&
            result.account_saved === true &&
            result.billing_status !== "unknown" &&
            !badSelection
          )
            state.ok += 1
          else {
            fail(username, result.reason || t("Регистрация не подтверждена"))
            useAccountsRun.getState().requestStop()
          }
          await refreshAccounts()
        } else if (kind === "login") {
          const res = await loginAccount(username)
          if (res.ok) state.ok += 1
          else if (res.banned)
            state.banned.push({
              username,
              reason: res.reason || t("аккаунта нет"),
            })
          else fail(username, res.reason || "")
          if (res.ok && res.warning) state.warnings.push({ username, reason: res.warning })
          if (res.identity_conflict) applyProfileRows({ [username]: { identity_conflict: true } }, undefined)
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
        if (kind === "register") {
          useAccountsRun.getState().requestStop()
          useAccountsRun.setState((store) => ({
            registrationResults: [
              ...store.registrationResults,
              {
                status:
                  error instanceof ApiError &&
                  error.status >= 400 &&
                  error.status < 500
                    ? "failed"
                    : "interrupted_or_unknown",
                reason:
                  error instanceof Error
                    ? error.message
                    : t("Результат регистрации неизвестен"),
              },
            ],
          }))
        }
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
      ...state.warnings.map((w) => `${w.username}: ${w.reason}`),
    ]
    const bad = state.failed.length + state.banned.length + state.warnings.length
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
