import { useEffect, useState } from "react"

/* Автосохранение без кнопки «Сохранить» — одно на все экраны. Значение уходит
   на сервер после паузы в правке; пока запрос в полёте, новые правки копятся и
   уходят одним запросом следом; то же самое второй раз не отправляется.
   flush() — отправить сейчас (уход из поля, Enter). */

export interface AutosaveOptions<T> {
  /** пауза после правки, мс */
  delay?: number
  /** не отправлять, пока false (например, форма ещё не получена с сервера) */
  enabled?: boolean
  /** сравнение с уже отправленным; по умолчанию — JSON */
  serialize?: (value: T) => string
  onError?: (error: unknown) => void
}

interface Latest<T> {
  value: T
  save: (value: T) => Promise<unknown>
  serialize: (value: T) => string
  onError?: (error: unknown) => void
}

function createSaver<T>() {
  let latest: Latest<T> | null = null
  let sent: string | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let inflight = false
  let dirty = false
  /* Готово ли значение к отправке (enabled у хука). Сторож не только на
     расписании: до первой отрисовки с настоящим значением `latest` держит
     пустышку, и flush(), позванный из чужого эффекта между отрисовками, увёз бы
     её на сервер. Так список прокси затирался пустой строкой (T-201). */
  let ready = false
  let onSaving: (saving: boolean) => void = () => {}

  const clearTimer = () => {
    if (timer) clearTimeout(timer)
    timer = null
  }

  async function flush(): Promise<void> {
    clearTimer()
    if (!latest || !ready) return
    if (inflight) {
      dirty = true
      return
    }
    const { value, save, serialize, onError } = latest
    const json = serialize(value)
    if (json === sent) return
    inflight = true
    onSaving(true)
    try {
      await save(value)
      sent = json
    } catch (error) {
      // не записалось — следующая правка попробует снова
      sent = null
      onError?.(error)
    } finally {
      inflight = false
      onSaving(false)
      if (dirty) {
        dirty = false
        void flush()
      }
    }
  }

  return {
    flush,
    setLatest: (next: Latest<T>) => {
      latest = next
    },
    /** значение готово (форма пришла с сервера) — до этого не отправляем ничего */
    setReady: (next: boolean) => {
      ready = next
    },
    schedule: (json: string, delay: number) => {
      if (!ready || json === sent) return
      clearTimer()
      timer = setTimeout(() => void flush(), delay)
    },
    /** значение уже на сервере (пришло оттуда) — назад его не отправлять */
    markSaved: (value: T) => {
      if (latest) sent = latest.serialize(value)
    },
    /** уход с экрана посреди паузы — несохранённое не теряем */
    flushPending: () => {
      if (timer) void flush()
    },
    subscribe: (fn: (saving: boolean) => void) => {
      onSaving = fn
    },
  }
}

export function useAutosave<T>(
  value: T,
  save: (value: T) => Promise<unknown>,
  { delay = 600, enabled = true, serialize = JSON.stringify, onError }: AutosaveOptions<T> = {}
) {
  const [saver] = useState(() => createSaver<T>())
  const [saving, setSaving] = useState(false)
  const json = serialize(value)

  useEffect(() => saver.subscribe(setSaving), [saver])
  useEffect(() => {
    saver.setLatest({ value, save, serialize, onError })
  })
  useEffect(() => {
    saver.setReady(enabled)
  }, [saver, enabled])
  useEffect(() => {
    if (enabled) saver.schedule(json, delay)
  }, [saver, json, enabled, delay])
  useEffect(() => () => saver.flushPending(), [saver])

  return { saving, flush: saver.flush, markSaved: saver.markSaved }
}
