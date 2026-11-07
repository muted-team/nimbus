import { useState } from "react"

/* Поле, живущее в паре с сервером: набранное не перебивается ответом, пока в
   поле курсор. Уход из поля сначала отправляет правку (commit), потом поле
   показывает записанное на сервере — тот зажимает числа в допустимые пределы,
   и поле должно показывать реальное значение, а не то, что набрали. */

export function useSyncedInput(server: string, commit: () => void) {
  const [value, setValue] = useState(server)
  const [focused, setFocused] = useState(false)
  const [applied, setApplied] = useState(server)

  // сервер ответил — показать его значение, если поле без курсора
  if (applied !== server && !focused) {
    setApplied(server)
    setValue(server)
  }

  return {
    value,
    onChange: setValue,
    onFocus: () => setFocused(true),
    onBlur: () => {
      commit()
      setFocused(false)
      setValue(server)
    },
  }
}
