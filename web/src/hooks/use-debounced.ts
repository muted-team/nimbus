import { useEffect, useState } from "react"

/* Значение, отстающее от набора: пока в поле печатают, запрос по каждой букве
   не уходит. Первое значение отдаётся сразу — экран открывается с данными. */

export function useDebounced<T>(value: T, delay = 400): T {
  const [slow, setSlow] = useState(value)

  useEffect(() => {
    if (Object.is(slow, value)) return
    const timer = setTimeout(() => setSlow(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay, slow])

  return slow
}
