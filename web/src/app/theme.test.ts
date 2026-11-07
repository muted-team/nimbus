import { existsSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import { runInNewContext } from "node:vm"
import { describe, expect, it } from "vitest"

interface Snapshot {
  mode: string
  resolved: string
}
interface Controller {
  getSnapshot: () => Snapshot
  setMode: (mode: string) => void
  subscribe: (listener: () => void) => () => void
}

function boot(
  initialDark = false,
  stored: string | null = null,
  blocked = false
) {
  const values = new Map<string, string>()
  if (stored !== null) values.set("ttwa.theme", stored)
  const mediaListeners = new Set<() => void>()
  const storageListeners = new Set<
    (event: { key: string | null; newValue: string | null }) => void
  >()
  const classes = new Set<string>()
  const root = {
    classList: {
      toggle: (name: string, on: boolean) =>
        on ? classes.add(name) : classes.delete(name),
    },
    dataset: {} as Record<string, string>,
    style: {} as Record<string, string>,
  }
  const meta = new Map<string, string>()
  const media = {
    matches: initialDark,
    addEventListener: (_: string, listener: () => void) =>
      mediaListeners.add(listener),
    removeEventListener: (_: string, listener: () => void) =>
      mediaListeners.delete(listener),
  }
  const window: {
    __ttwaTheme?: Controller
    matchMedia: () => typeof media
    localStorage: object
    addEventListener: Function
  } = {
    matchMedia: () => media,
    localStorage: {
      getItem: (key: string) => {
        if (blocked) throw new Error("storage blocked")
        return values.get(key) ?? null
      },
      setItem: (key: string, value: string) => {
        if (blocked) throw new Error("storage blocked")
        values.set(key, value)
      },
    },
    addEventListener: (
      _: string,
      listener: (event: { key: string | null; newValue: string | null }) => void
    ) => storageListeners.add(listener),
  }
  const path = resolve("public/theme.js")
  runInNewContext(existsSync(path) ? readFileSync(path, "utf8") : "", {
    window,
    document: {
      documentElement: root,
      querySelector: (query: string) => ({
        setAttribute: (_: string, value: string) => meta.set(query, value),
      }),
    },
  })
  return {
    window,
    root,
    classes,
    meta,
    values,
    media,
    mediaListeners,
    storageListeners,
  }
}

describe("interface theme", () => {
  it("starts in system mode with the current light appearance before React loads", () => {
    const app = boot()
    expect(app.window.__ttwaTheme?.getSnapshot()).toEqual({
      mode: "system",
      resolved: "light",
    })
    expect(app.classes.has("dark")).toBe(false)
    expect(app.root.style.colorScheme).toBe("light")
  })

  it("follows system changes without changing the saved mode and notifies subscribers", () => {
    const app = boot(true)
    const controller = app.window.__ttwaTheme!
    let notifications = 0
    const unsubscribe = controller.subscribe(() => notifications++)
    expect(controller.getSnapshot()).toEqual({
      mode: "system",
      resolved: "dark",
    })
    app.media.matches = false
    app.mediaListeners.forEach((listener) => listener())
    expect(controller.getSnapshot()).toEqual({
      mode: "system",
      resolved: "light",
    })
    expect(app.classes.has("dark")).toBe(false)
    expect(notifications).toBe(1)
    unsubscribe()
    app.media.matches = true
    app.mediaListeners.forEach((listener) => listener())
    expect(notifications).toBe(1)
  })

  it("loads and saves explicit choices independently of the system appearance", () => {
    const app = boot(true, "light")
    const controller = app.window.__ttwaTheme!
    expect(controller.getSnapshot()).toEqual({
      mode: "light",
      resolved: "light",
    })
    controller.setMode("dark")
    expect(app.values.get("ttwa.theme")).toBe("dark")
    expect(app.classes.has("dark")).toBe(true)
    app.media.matches = false
    app.mediaListeners.forEach((listener) => listener())
    expect(controller.getSnapshot()).toEqual({ mode: "dark", resolved: "dark" })
    controller.setMode("system")
    expect(controller.getSnapshot()).toEqual({
      mode: "system",
      resolved: "light",
    })
    expect(app.values.get("ttwa.theme")).toBe("system")
    expect(app.meta.get('meta[name="color-scheme"]')).toBe("light")
    expect(app.meta.get('meta[name="theme-color"]')).toBe("#fafafa")
  })

  it("falls back to system for invalid stored choices and works when storage is blocked", () => {
    const invalid = boot(true, "unexpected")
    expect(invalid.window.__ttwaTheme?.getSnapshot()).toEqual({
      mode: "system",
      resolved: "dark",
    })
    const blocked = boot(false, "dark", true)
    expect(blocked.window.__ttwaTheme?.getSnapshot()).toEqual({
      mode: "system",
      resolved: "light",
    })
    blocked.window.__ttwaTheme!.setMode("dark")
    expect(blocked.classes.has("dark")).toBe(true)
  })

  it("reflects another tab's choice and a cleared preference", () => {
    const app = boot(false)
    app.storageListeners.forEach((listener) =>
      listener({ key: "ttwa.theme", newValue: "dark" })
    )
    expect(app.window.__ttwaTheme?.getSnapshot()).toEqual({
      mode: "dark",
      resolved: "dark",
    })
    app.storageListeners.forEach((listener) =>
      listener({ key: "unrelated", newValue: "light" })
    )
    expect(app.classes.has("dark")).toBe(true)
    app.storageListeners.forEach((listener) =>
      listener({ key: null, newValue: null })
    )
    expect(app.window.__ttwaTheme?.getSnapshot()).toEqual({
      mode: "system",
      resolved: "light",
    })
  })
})
