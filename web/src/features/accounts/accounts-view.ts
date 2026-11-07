import { create } from "zustand"

import { pick, prune, type PickMode } from "@/lib/selection"

import type { ColumnKey } from "./columns"
import { defaultDir, type AccountsFilter, type SortDir, type SortKey } from "./filter"

/* Контракт экрана: открытый срез списка, порядок строк, поиск и выделение —
   живут здесь, а не в компоненте, чтобы сводка публикации могла поставить срез перед
   переходом, а выделение не терялось при уходе с экрана и возврате.

   Срез, порядок и спрятанные колонки переживают перезапуск программы:
   человек один раз настроил себе вид списка, и каждое утро возвращать его
   обратно не надо. Поиск и выделение не сохраняются — это разовое. */

const STORE_KEY = "accounts.view"

const FILTERS: AccountsFilter[] = ["ready", "all", "nologin", "shadow", "banned"]
const SORT_KEYS: SortKey[] = ["name", "region", "followers", "likes", "views", "posts", "shadow", "fetched"]

interface SavedView {
  filter: AccountsFilter
  sort: SortKey
  dir: SortDir
  hidden: ColumnKey[]
}

const DEFAULTS: SavedView = { filter: "ready", sort: "name", dir: "asc", hidden: [] }

/* Хранилище может быть недоступно (приватное окно, запрет на данные сайта) —
   тогда просто работаем с настройками по умолчанию. */
function loadView(): SavedView {
  try {
    const raw = window.localStorage.getItem(STORE_KEY)
    if (!raw) return DEFAULTS
    const saved = JSON.parse(raw) as Partial<SavedView>
    return {
      filter: FILTERS.includes(saved.filter!) ? saved.filter! : DEFAULTS.filter,
      sort: SORT_KEYS.includes(saved.sort!) ? saved.sort! : DEFAULTS.sort,
      dir: saved.dir === "asc" || saved.dir === "desc" ? saved.dir : DEFAULTS.dir,
      hidden: Array.isArray(saved.hidden)
        ? (saved.hidden as string[]).filter((k): k is ColumnKey => k !== "name" && (SORT_KEYS as string[]).includes(k))
        : DEFAULTS.hidden,
    }
  } catch {
    return DEFAULTS
  }
}

function saveView(view: SavedView) {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(view))
  } catch {
    // не сохранилось — вид просто не переживёт перезапуск
  }
}

interface AccountsViewState extends SavedView {
  query: string
  selected: Set<string>
  /** последняя кликнутая строка — от неё тянется рамка Shift */
  anchor: string | null
  /** выделение до первого Shift-клика: рамка собирается поверх него */
  rangeBase: Set<string> | null
  /** открытая карточка аккаунта; её же открывает палитра команд */
  card: string | null
  setCard: (username: string | null) => void
  setFilter: (filter: AccountsFilter) => void
  /** та же колонка — разворот порядка, другая — её обычный порядок */
  setSort: (key: SortKey) => void
  setQuery: (query: string) => void
  /** показать или спрятать колонку (меню «Колонки») */
  toggleColumn: (key: ColumnKey) => void
  /** клик по строке: solo — единственное выделение, toggle — Ctrl, range — Shift */
  select: (username: string, mode: PickMode, usernames: string[]) => void
  selectAll: (usernames: string[]) => void
  clearSelection: () => void
  /** убрать из выделения usernames, которых уже нет в списке */
  pruneSelection: (usernames: string[]) => void
}

export const useAccountsView = create<AccountsViewState>((set, get) => ({
  ...loadView(),
  query: "",
  selected: new Set(),
  anchor: null,
  rangeBase: null,
  card: null,
  setCard: (card) => set({ card }),
  /* Другой срез — другой список: выделение из прежнего сбрасывается, иначе
     панель действует по аккаунтам, которых на экране нет (T-178). Поиск
     выделение не трогает — им добирают строки к уже выбранным. */
  setFilter: (filter) => {
    const { sort, dir, hidden } = get()
    saveView({ filter, sort, dir, hidden })
    if (filter === get().filter) return
    set({ filter, selected: new Set(), rangeBase: null, anchor: null })
  },
  setSort: (key) => {
    const { filter, sort, dir, hidden } = get()
    const next: SavedView =
      key === sort
        ? { filter, sort, dir: dir === "asc" ? "desc" : "asc", hidden }
        : { filter, sort: key, dir: defaultDir(key), hidden }
    saveView(next)
    set({ sort: next.sort, dir: next.dir })
  },
  toggleColumn: (key) => {
    const { filter, sort, dir, hidden } = get()
    const next = hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key]
    saveView({ filter, sort, dir, hidden: next })
    set({ hidden: next })
  },
  setQuery: (query) => set({ query }),
  select: (username, mode, usernames) => {
    const { selected, anchor, rangeBase } = get()
    set(pick({ selected, anchor, rangeBase }, username, mode, usernames))
  },
  selectAll: (usernames) => set({ selected: new Set(usernames), rangeBase: null }),
  clearSelection: () => set({ selected: new Set(), rangeBase: null }),
  pruneSelection: (usernames) => {
    const { selected, anchor, rangeBase } = get()
    const state = { selected, anchor, rangeBase }
    const next = prune(state, usernames)
    if (next !== state) set({ selected: next.selected })
  },
}))
