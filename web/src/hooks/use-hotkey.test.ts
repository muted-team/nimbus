import { describe, expect, it } from "vitest"

import { hotkeyKeys } from "./use-hotkey"

/* Подсказка у кнопки показывает клавиши сочетания так, как они написаны на
   клавиатуре: Ctrl, ⏎, Esc — а не коды событий. */

describe("hotkeyKeys", () => {
  it("сочетание с Mod и Enter", () => {
    expect(hotkeyKeys("Mod+Enter")).toEqual(["Ctrl", "⏎"])
  })

  it("одиночные клавиши и буквы", () => {
    expect(hotkeyKeys("Escape")).toEqual(["Esc"])
    expect(hotkeyKeys("Mod+b")).toEqual(["Ctrl", "B"])
  })
})
