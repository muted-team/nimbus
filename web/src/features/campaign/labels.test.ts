import { describe, expect, it } from "vitest"

import { OUTCOME_LABEL, RESULTS_LABEL, SHORTAGE_LABEL } from "./labels"

/* Число снятых за нарушение правил постов стоит на экране публикации дважды:
   в строке «Отчёт» это аккаунты, в панели результатов — сами посты. Одинаковая
   подпись у обоих читалась бы как одна величина, названная дважды, поэтому
   каждое число подписано тем, что считает. */

describe("снятые за нарушение правил: аккаунты и посты", () => {
  it("в строке «Отчёт» число подписано аккаунтами", () => {
    expect(OUTCOME_LABEL.removed.label(1)).toBe("Снято за нарушение правил: 1 аккаунт")
    expect(OUTCOME_LABEL.removed.label(2)).toBe("Снято за нарушение правил: 2 аккаунта")
    expect(OUTCOME_LABEL.removed.label(7)).toBe("Снято за нарушение правил: 7 аккаунтов")
  })

  it("в панели результатов число подписано постами", () => {
    expect(RESULTS_LABEL.removed(1)).toBe("Снято за нарушение правил: 1 пост")
    expect(RESULTS_LABEL.removed(2)).toBe("Снято за нарушение правил: 2 поста")
    expect(RESULTS_LABEL.removed(7)).toBe("Снято за нарушение правил: 7 постов")
  })

  it("одно и то же число читается по-разному — по аккаунтам и по постам", () => {
    expect(OUTCOME_LABEL.removed.label(2)).not.toBe(RESULTS_LABEL.removed(2))
  })

  it("остальные исходы в строке «Отчёт» подписаны словом и числом", () => {
    expect(OUTCOME_LABEL.published.label(12)).toBe("Опубликовано 12")
    expect(OUTCOME_LABEL.failed.label(3)).toBe("Не опубликовано 3")
    expect(OUTCOME_LABEL.banned.label(1)).toBe("Забанено 1")
  })
})

/* Нехватку файлов видно до запуска: у папки и в подтверждении. Число в обоих
   местах одно и то же, поэтому и текст один — «нужно столько-то, есть
   столько-то». */

describe("нехватка файлов в папке", () => {
  it("в подтверждении запуска названы и нужное число, и наличное", () => {
    expect(SHORTAGE_LABEL.need("photo", 300, 45)).toBe("нужно 300 фото, есть 45")
    expect(SHORTAGE_LABEL.need("video", 50, 7)).toBe("нужно 50 видео, есть 7")
  })

  it("у строки папки сказано, чего именно не хватит", () => {
    expect(SHORTAGE_LABEL.row("photo", 300, 45)).toBe("Не хватит: нужно 300 фото, есть 45")
  })

  it("папка-слот названа номером, а у видео она одна", () => {
    expect(SHORTAGE_LABEL.folder("photo", 0)).toBe("Папка 1")
    expect(SHORTAGE_LABEL.folder("photo", 2)).toBe("Папка 3")
    expect(SHORTAGE_LABEL.folder("video", 0)).toBe("Папка")
  })
})
