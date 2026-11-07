import { t } from "@/lib/i18n"
import { userMessage } from "@/api/client"
import { useEffect } from "react"
import { toast } from "sonner"

import { applyProfileRows, refreshAccounts, setProfilesStatus } from "./accounts"
import { setCampaignStatus } from "./campaign"
import { useLogs } from "./logs"
import { applyProxyHealth } from "./proxies"
import { keys, queryClient } from "./query-client"
import type { CampaignStatus, LogItem, Profile, ProfilesStatus, ProxyHealth } from "./types"

/* Живой поток интерфейса (GET /api/stream, Server-Sent Events): журнал,
   прогресс публикации, ход обновления профилей со свежими строками аккаунтов и
   отметки проверки прокси — в момент изменения. У потока своё соединение;
   после обрыва браузер переподключается сам. */

function parse<T>(data: string): T | null {
  try {
    return JSON.parse(data) as T
  } catch {
    return null
  }
}

interface ProfilesEvent {
  status?: ProfilesStatus
  profiles?: Record<string, Profile>
  avatars?: Record<string, { at: number; data: string }>
}

function profilesToast(st: ProfilesStatus) {
  if (st.error) {
    toast.error(t("Профили не обновлены: {0}.", [userMessage(st.error)]))
    return
  }
  const failed = st.failed ?? []
  if (!failed.length) {
    toast.success(t("Профили обновлены: {0}.", [st.ok]))
    return
  }
  const shown = failed.slice(0, 3).map((f) => `${f.username}: ${userMessage(f.reason)}.`)
  const rest = failed.length > 3 ? t("И ещё {0}.", [failed.length - 3]) : ""
  const notify = st.ok ? toast.warning : toast.error
  notify(t("Профили обновлены: {0} из {1}.", [st.ok, st.total]), {
    description: [...shown, rest].filter(Boolean).join("\n"),
  })
}

/** Снимок хода обновления профилей; закончилось — перечитать список и итог тостом. */
export function applyProfilesStatus(next: ProfilesStatus) {
  const prev = queryClient.getQueryData<ProfilesStatus>(keys.profilesRefresh)
  const applied = setProfilesStatus(next)
  if (prev?.running && applied !== prev && !applied.running) {
    void refreshAccounts()
    profilesToast(applied)
  }
}

/** Подключает поток на всё время жизни приложения. */
export function useLiveStream(enabled: boolean) {
  const debug = useLogs((s) => s.debug)

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return
    let source: EventSource | null = null
    let closed = false

    const open = () => {
      const { seq, boot } = useLogs.getState()
      source?.close()
      source = new EventSource(
        `api/stream?after=${seq}&debug=${debug ? 1 : 0}&boot=${encodeURIComponent(boot)}`
      )

      source.addEventListener("hello", (e) => {
        const boot = (e as MessageEvent<string>).data
        const logs = useLogs.getState()
        const restarted = logs.boot && logs.boot !== boot
        logs.setBoot(boot)
        if (restarted && !closed) {
          // переоткрываем с новым номером запуска: иначе каждое
          // переподключение тянуло бы весь буфер заново
          logs.forgetSeq()
          open()
        }
      })
      source.addEventListener("campaign", (e) => {
        const st = parse<CampaignStatus>((e as MessageEvent<string>).data)
        if (st) setCampaignStatus(st)
      })
      source.addEventListener("profiles", (e) => {
        const ev = parse<ProfilesEvent>((e as MessageEvent<string>).data)
        if (!ev) return
        // строки раньше хода: спиннер снимается в той же перерисовке, где
        // встали новые цифры
        applyProfileRows(ev.profiles, ev.avatars)
        if (ev.status) applyProfilesStatus(ev.status)
      })
      source.addEventListener("proxies", (e) => {
        const ev = parse<{ health?: ProxyHealth[] }>((e as MessageEvent<string>).data)
        if (ev?.health) applyProxyHealth(ev.health)
      })
      source.onmessage = (e) => {
        const items = parse<LogItem[]>(e.data)
        if (items) useLogs.getState().merge(items)
      }
    }

    open()
    return () => {
      closed = true
      source?.close()
    }
  }, [enabled, debug])
}
