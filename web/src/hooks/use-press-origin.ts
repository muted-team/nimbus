import { useRef } from "react"

/* Щелчок строки — только тот, что начался и кончился на самой строке.

   Два пути, которыми чужой щелчок доставался строке:
   - меню закрывается, пока кнопка ещё нажата над пунктом, и событие click
     уходит уже строке под ним;
   - меню «…» отрисовано порталом, но в дереве React живёт внутри строки, и
     щелчок по его пункту всплывает до строки, хотя на экране пункт лежит
     вне её.
   Оба открывали карточку аккаунта или меняли выбор прокси. Поэтому строка
   берёт щелчок, только если и нажатие, и сам щелчок пришлись на её узлы в
   DOM, а нажата была левая кнопка. */

const inside = (e: React.SyntheticEvent) => e.currentTarget.contains(e.target as Node)

export function usePressOrigin() {
  const pressed = useRef(false)
  return {
    onPointerDown: (e: React.PointerEvent) => {
      pressed.current = e.button === 0 && inside(e)
    },
    /** щелчок начат и закончен на этой строке; признак снимается */
    take: (e: React.MouseEvent) => {
      const here = pressed.current && inside(e)
      pressed.current = false
      return here
    },
  }
}
