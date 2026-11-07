import { create } from "zustand"
import { persist } from "zustand/middleware"

/* Удобства конкретного браузера: свёрнуто ли меню, последний открытый раздел.
   Настройки программы живут на сервере, а не здесь. */

interface PrefsState {
  sidebarOpen: boolean
  lastPath: string
  setSidebarOpen: (open: boolean) => void
  setLastPath: (path: string) => void
}

export const usePrefs = create<PrefsState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      lastPath: "/",
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
      setLastPath: (lastPath) => set({ lastPath }),
    }),
    { name: "ttwa.prefs" }
  )
)
