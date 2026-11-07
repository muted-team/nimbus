import { describe, expect, it } from "vitest"

import type { MediaKind, SlotInfo } from "@/api/types"

import type { FormValues } from "./form-model"
import { filesPerFolder, findShortage } from "./shortage"

/* Хватает ли файлов на проход — правило расхода из modules/batch_publish.py:
   разные креативы берут свой файл на каждый пост, одинаковые держат один
   комплект на весь прогон аккаунта, а те, что велено оставлять, идут по кругу. */

function form(patch: Partial<FormValues> = {}): FormValues {
  return {
    media: "photo",
    title: "",
    caption: "",
    photoSlots: ["C:\\slots\\1"],
    videoSlots: [],
    posts: "6",
    delayMin: "",
    delayMax: "",
    creatives: "copies",
    keep: false,
    cleanup: false,
    cleanupMode: "same",
    cleanupCount: "",
    repeat: false,
    repeatMin: "",
    repeatMax: "",
    repeatUnit: "hour",
    ...patch,
  }
}

/** Числа по папкам, как их отдаёт /api/slots: файлов — по одному числу на папку. */
function slotInfo(paths: string[], counts: number[], media: MediaKind = "photo"): Map<string, SlotInfo> {
  return new Map(
    paths.map((path, i) => [
      path,
      { path, exists: true, photos: media === "photo" ? counts[i] : 0, videos: media === "video" ? counts[i] : 0 },
    ])
  )
}

describe("сколько файлов нужно в папке", () => {
  it("разные креативы — свой файл на каждый пост", () => {
    expect(filesPerFolder("unique", 6, 50, false)).toBe(300)
    expect(filesPerFolder("unique", 1, 1, false)).toBe(1)
  })

  it("одинаковые креативы — комплект держится весь прогон аккаунта", () => {
    expect(filesPerFolder("copies", 6, 50, false)).toBe(50)
    expect(filesPerFolder("single", 6, 50, false)).toBe(50)
  })

  it("файлы велено оставлять — идут по кругу, нужен хотя бы один", () => {
    expect(filesPerFolder("unique", 6, 50, true)).toBe(1)
    expect(filesPerFolder("copies", 6, 50, true)).toBe(1)
  })

  it("аккаунтов ещё не знаем — считать нечего", () => {
    expect(filesPerFolder("copies", 6, undefined, false)).toBeNull()
    expect(filesPerFolder("unique", 6, 0, false)).toBeNull()
  })
})

describe("у какой папки файлов не хватит", () => {
  const slots = ["C:\\slots\\1", "C:\\slots\\2"]

  it("разных креативов не хватает: нужно аккаунты × постов на аккаунт", () => {
    const values = form({ creatives: "unique", photoSlots: slots })
    expect(findShortage(values, slotInfo(slots, [300, 45]), 50)).toEqual([{ index: 1, need: 300, have: 45 }])
  })

  it("одинаковых креативов нужно по файлу на аккаунт", () => {
    const values = form({ photoSlots: slots })
    expect(findShortage(values, slotInfo(slots, [50, 49]), 50)).toEqual([{ index: 1, need: 50, have: 49 }])
  })

  it("файлов хватает — предупреждения нет", () => {
    const values = form({ creatives: "unique", photoSlots: slots })
    expect(findShortage(values, slotInfo(slots, [300, 480]), 50)).toEqual([])
  })

  it("файлы велено оставлять — хватает одного, пустая папка всё равно видна", () => {
    const values = form({ creatives: "unique", photoSlots: slots, keep: true })
    expect(findShortage(values, slotInfo(slots, [1, 0]), 50)).toEqual([{ index: 1, need: 1, have: 0 }])
  })

  it("папка ещё не выбрана — предупреждения нет", () => {
    const values = form({ photoSlots: [] })
    expect(findShortage(values, slotInfo([], []), 50)).toEqual([])
  })

  it("папки на диске нет — молчит строка папки, а не счёт файлов", () => {
    const values = form({ photoSlots: slots })
    const info = slotInfo(slots, [0, 0])
    info.set(slots[0], { path: slots[0], exists: false, photos: 0, videos: 0 })
    expect(findShortage(values, info, 50)).toEqual([{ index: 1, need: 50, have: 0 }])
  })

  it("числа по папкам ещё не пришли — предупреждения нет", () => {
    expect(findShortage(form(), undefined, 50)).toEqual([])
  })

  it("у видео считаются ролики, а не фото", () => {
    const values = form({ media: "video", videoSlots: ["C:\\video"] })
    const info = slotInfo(["C:\\video"], [7], "video")
    expect(findShortage(values, info, 50)).toEqual([{ index: 0, need: 50, have: 7 }])
  })

  it("счёт постов набран с ошибкой — файлов не считаем", () => {
    expect(findShortage(form({ posts: "" }), slotInfo(["C:\\slots\\1"], [0]), 50)).toEqual([])
  })
})

/* Строка формы рисуется по сырому списку папок (включая пустые), а не по
   списку без пустых строк: очистив верхнее поле, короткая папка не должна
   потерять предупреждение и не должна встать под чужой (пустой) строкой.
   Индекс здесь — это и номер строки на экране (SlotRow), и номер «Папки N» в
   подтверждении запуска, поэтому оба места обязаны видеть одно и то же число. */
describe("индекс не разъезжается с пустыми строками", () => {
  it("пустая строка сверху — короткая папка снизу сохраняет свой (второй) номер", () => {
    const slots = ["", "C:\\slots\\2"]
    const values = form({ creatives: "unique", photoSlots: slots })
    expect(findShortage(values, slotInfo(slots, [0, 45]), 50)).toEqual([{ index: 1, need: 300, have: 45 }])
  })

  it("пустая строка посередине — номера папок после неё не сдвигаются", () => {
    const slots = ["C:\\slots\\1", "", "C:\\slots\\3"]
    const values = form({ creatives: "unique", photoSlots: slots })
    // без пустой строки activeSlots() дал бы этой папке индекс 1, а не 2
    expect(findShortage(values, slotInfo(slots, [300, 0, 45]), 50)).toEqual([{ index: 2, need: 300, have: 45 }])
  })

  it("несколько папок, пустая строка между ними — у каждой свой сырой номер", () => {
    const slots = ["C:\\slots\\1", "", "C:\\slots\\3"]
    const values = form({ creatives: "unique", photoSlots: slots })
    expect(findShortage(values, slotInfo(slots, [10, 0, 20]), 50)).toEqual([
      { index: 0, need: 300, have: 10 },
      { index: 2, need: 300, have: 20 },
    ])
  })
})
