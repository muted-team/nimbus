import { create } from "zustand"
import { persist } from "zustand/middleware"

import { api } from "./client"
import type { LogItem } from "./types"

export const MAX_EVENTS = 500

interface LogState {
  /** новые сверху */
  events: LogItem[]
  /** номер последней прочитанной записи сервера */
  seq: number
  /** номер запуска сервера, к которому относятся номера записей */
  boot: string
  /** «Подробно»: и stdout модулей, не только события */
  debug: boolean
  /** номер записи, до которой ошибки уже видели на экране логов */
  seenSeq: number
  merge: (items: LogItem[]) => void
  /** журнал очищен на сервере: стереть локальный список (seq и boot не
      трогаем — сервер их не сбрасывает, см. modules/eventlog.py clear()) */
  clear: () => void
  /** запись самого интерфейса (неудачный запрос) — в подробности */
  pushLocal: (source: string, text: string) => void
  /** сервер перезапустился: его нумерация пошла заново */
  forgetSeq: () => void
  setBoot: (boot: string) => void
  setDebug: (debug: boolean) => void
  markSeen: () => void
}

const byTime = (a: LogItem, b: LogItem) => b.ts - a.ts || b.seq - a.seq

export const useLogs = create<LogState>()(
  persist(
    (set, get) => ({
      events: [],
      seq: 0,
      boot: "",
      debug: false,
      seenSeq: 0,
      merge: (items) => {
        if (!items.length) return
        const { events, seq } = get()
        const known = new Set(events.filter((e) => e.seq).map((e) => e.seq))
        let last = seq
        const fresh: LogItem[] = []
        for (const it of items) {
          if (it.seq > last) last = it.seq
          if (!it.seq || known.has(it.seq)) continue
          known.add(it.seq)
          fresh.push(it)
        }
        if (!fresh.length) {
          if (last !== seq) set({ seq: last })
          return
        }
        const next = fresh.concat(events).sort(byTime).slice(0, MAX_EVENTS)
        set({ events: next, seq: last })
      },
      pushLocal: (source, text) =>
        set(({ events }) => ({
          events: [
            { seq: 0, ts: Date.now() / 1000, level: "err" as const, debug: true, source, text },
            ...events,
          ].slice(0, MAX_EVENTS),
        })),
      forgetSeq: () =>
        set(({ events }) => ({ events: events.map((e) => ({ ...e, seq: 0 })), seq: 0, seenSeq: 0 })),
      clear: () => set({ events: [] }),
      setBoot: (boot) => set({ boot }),
      // подробностей у клиента нет — без флага сервер их не шлёт: перечитываем
      // журнал с начала буфера, свои записи интерфейса оставляем
      setDebug: (debug) =>
        set(({ events }) => ({ debug, seq: 0, events: events.filter((e) => !e.seq) })),
      markSeen: () => set(({ seq }) => ({ seenSeq: seq })),
    }),
    {
      name: "ttwa.logs",
      // seenSeq хранится вместе с boot: номер записи имеет смысл только
      // относительно запуска сервера, к которому относится — при смене
      // запуска forgetSeq() сбрасывает оба поля (см. api/stream.ts)
      partialize: (s) => ({ debug: s.debug, boot: s.boot, seenSeq: s.seenSeq }),
    }
  )
)

/** Очистить журнал целиком: POST /api/logs/clear, затем стереть локальный
    список записей — иначе на экране остались бы уже удалённые на сервере. */
export async function clearLogs() {
  const res = await api.post<{ ok: boolean }>("api/logs/clear")
  useLogs.getState().clear()
  return res
}

/** Сколько ошибок пришло после последнего просмотра экрана логов.

    Поднятые из файла записи прошлого запуска (`past`) не считаются: `seenSeq`
    не переживает перезагрузку, и без этого значки показывали бы старые ошибки
    как свежие, пока владелец не откроет вкладку. */
export function unseenErrors(events: LogItem[], seenSeq: number): number {
  let n = 0
  for (const e of events) {
    if (e.seq && e.seq <= seenSeq) break
    if (e.seq && !e.debug && !e.past && e.level === "err") n += 1
  }
  return n
}
