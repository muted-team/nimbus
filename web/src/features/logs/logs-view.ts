import { create } from "zustand"

import type { LevelFilter } from "./log-filter"

/* Состояние раздела «Журнал»: срез по уровню, поиск и аккаунт. Живёт здесь,
   а не в компоненте: возврат на экран не сбрасывает выбранный срез, а другие
   экраны могут открыть журнал сразу на нужном. */

interface LogsViewState {
  level: LevelFilter
  search: string
  /** журнал одного аккаунта; null — весь */
  account: string | null
  setLevel: (level: LevelFilter) => void
  setSearch: (search: string) => void
  setAccount: (account: string | null) => void
}

export const useLogsView = create<LogsViewState>((set) => ({
  level: "all",
  search: "",
  account: null,
  setLevel: (level) => set({ level }),
  setSearch: (search) => set({ search }),
  setAccount: (account) => set({ account }),
}))
