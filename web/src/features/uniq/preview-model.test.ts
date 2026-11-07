import { describe, expect, it } from "vitest"

import { PREVIEW_EMPTY, previewEmpty } from "./preview-model"

const PHOTO_FOLDERS = ["C:/photos"]

describe("previewEmpty", () => {
  it("в режиме видео фото-папки превью не собирают", () => {
    expect(previewEmpty("video", PHOTO_FOLDERS, true, true)).toBe("video")
    expect(previewEmpty("video", PHOTO_FOLDERS, true, false)).toBe("video")
    expect(previewEmpty("video", [], true, true)).toBe("video")
  })
  it("в режиме фото поведение прежнее", () => {
    expect(previewEmpty("photo", PHOTO_FOLDERS, true, true)).toBeNull()
    expect(previewEmpty("photo", [], true, true)).toBe("noFolders")
    expect(previewEmpty("photo", PHOTO_FOLDERS, true, false)).toBe("off")
  })
  it("пока форма не ответила — загрузка, а не текст", () => {
    expect(previewEmpty("photo", [], false, true)).toBe("loading")
    expect(previewEmpty("video", [], false, true)).toBe("loading")
  })
})

describe("PREVIEW_EMPTY", () => {
  it("видео объясняет то же, что инструкция", () => {
    expect(PREVIEW_EMPTY.video.title).toBe("К видео не применяется")
    expect(PREVIEW_EMPTY.video.text).toContain("Ролик уходит в TikTok как есть")
  })
  it("тексты режима фото не изменились", () => {
    expect(PREVIEW_EMPTY.noFolders.title).toBe("Папки не выбраны")
    expect(PREVIEW_EMPTY.off.title).toBe("Уникализация выключена")
  })
})
