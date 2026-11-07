import { useEffect, useState } from "react"

/* Текущее время, обновляемое таймером: нужно там, где на экране идёт отсчёт
   («Следующий круг через 2 ч 15 мин»). Сервер присылает срок один раз, и без
   своего таймера цифра стояла бы на месте до следующего снимка. */

export function useNow(intervalMs = 1000, enabled = true): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!enabled) return
    // вкладка не видна — цифру всё равно никто не читает
    const tick = () => {
      if (!document.hidden) setNow(Date.now())
    }
    // первый тик сразу: отсчёт мог простоять выключенным и отстать
    const first = setTimeout(tick, 0)
    const timer = setInterval(tick, intervalMs)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [intervalMs, enabled])

  return now
}
