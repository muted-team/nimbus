import { useSyncExternalStore } from "react"

export type ThemeMode = "system" | "light" | "dark"
interface ThemeSnapshot {
  mode: ThemeMode
  resolved: "light" | "dark"
}
interface ThemeController {
  getSnapshot: () => ThemeSnapshot
  setMode: (mode: ThemeMode) => void
  subscribe: (listener: () => void) => () => void
}

declare global {
  interface Window {
    __ttwaTheme: ThemeController
  }
}

export function useTheme() {
  return useSyncExternalStore(
    window.__ttwaTheme.subscribe,
    window.__ttwaTheme.getSnapshot
  )
}

export function setTheme(mode: ThemeMode) {
  window.__ttwaTheme.setMode(mode)
}
