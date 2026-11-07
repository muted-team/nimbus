import { afterEach, describe, expect, it, vi } from "vitest"

/* Подсказка у кнопки показывает клавиши сочетания так, как они написаны на
   клавиатуре: Ctrl, ⏎, Esc — а не коды событий. */

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe("hotkeyKeys", () => {
  it.each([ ["Win32", "Ctrl", "Alt"], ["MacIntel", "⌘", "⌥"] ])(
    "подсказки соответствуют клавиатуре %s", async (platform, mod, alt) => {
    vi.stubGlobal("navigator", { platform })
    vi.resetModules()
    const { hotkeyKeys } = await import("./use-hotkey")
    expect(hotkeyKeys("Mod+Enter")).toEqual([mod, "⏎"])
    expect(hotkeyKeys("Escape")).toEqual(["Esc"])
    expect(hotkeyKeys("Mod+b")).toEqual([mod, "B"])
    expect(hotkeyKeys("Alt+1")).toEqual([alt, "1"])
  })
})
