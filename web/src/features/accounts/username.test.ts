import { describe, expect, it } from "vitest"

import { COPY_LABEL } from "./labels"
import { atUsername, selectedUsernames, usernamesText } from "./username"

/* Что уходит в буфер: юзернейм — с собакой, как он выглядит в TikTok, а
   выделенные — столбиком, по одному в строке. Паролей, кодов 2FA и почт
   рядом с ними быть не должно — в буфер идут только юзернеймы. */

describe("юзернейм в буфере", () => {
  it("копируется с собакой", () => {
    expect(atUsername("kate")).toBe("@kate")
    expect(usernamesText(["kate"])).toBe("@kate")
  })

  it("выделенные идут столбиком в порядке строк списка", () => {
    expect(usernamesText(["one", "two", "three"])).toBe("@one\n@two\n@three")
  })

  it("пустой список в буфер ничего не кладёт", () => {
    expect(usernamesText([])).toBe("")
  })

  it("выделен один — тот же текст из одной строки", () => {
    expect(usernamesText(["solo"])).toBe(atUsername("solo"))
  })

  /* Срез и поиск выделение не сбрасывают: часть выделенных строк на экране
     скрыта. Счётчик панели называет всё выделение, и в буфер должно уходить
     ровно оно — иначе копируется меньше обещанного. */
  it("скрытые выделенные тоже уходят в буфер — следом за видимыми", () => {
    const picked = selectedUsernames(new Set(["hidden", "b"]), ["b", "c"], ["hidden", "b", "c"])
    expect(usernamesText(picked)).toBe("@b\n@hidden")
  })

  it("выделен единственный скрытый — в буфер есть что положить", () => {
    expect(selectedUsernames(new Set(["hidden"]), [], ["hidden"])).toEqual(["hidden"])
  })

  it("невыделенные в буфер не попадают", () => {
    expect(selectedUsernames(new Set(["b"]), ["a", "b"], ["a", "b"])).toEqual(["b"])
    expect(selectedUsernames(new Set(), ["a", "b"], ["a", "b"])).toEqual([])
  })
})

describe("подписи копирования", () => {
  it("пункт меню — одно слово что при одном, что при нескольких: число только в тосте", () => {
    expect(COPY_LABEL.one).toBe("Скопировать")
    expect(COPY_LABEL.many).toBe("Скопировать")
  })

  it("тост говорит, что легло в буфер", () => {
    expect(COPY_LABEL.toastOne).toBe("Юзернейм скопирован.")
    expect(COPY_LABEL.toastMany(4)).toBe("Скопировано юзернеймов: 4.")
  })
})
