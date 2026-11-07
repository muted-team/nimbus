import { localize, useLanguage } from "@/lib/i18n"
import { useMemo, useRef, useState } from "react"
import {
  CornerDownLeftIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SquareIcon,
  UserRoundIcon,
  type LucideIcon,
} from "lucide-react"
import { useLocation } from "wouter"

import { startProfilesRefresh, useAccounts } from "@/api/accounts"
import { Kbd } from "@/components/ui/kbd"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { useAccountsView } from "@/features/accounts/accounts-view"
import { atUsername } from "@/features/accounts/username"
import { useCampaignLauncher } from "@/features/campaign/launcher"
import { checkProxiesNow } from "@/features/proxies/proxies-store"
import { useHotkey } from "@/hooks/use-hotkey"
import { notify } from "@/lib/notify"
import { cn } from "@/lib/utils"

import { SECTIONS, sectionPath } from "./sections"

/* Палитра команд по Ctrl+K: разделы, частые действия и аккаунты по юзернейму
   в одном поиске. Стрелки ходят по списку, Enter выполняет, Esc закрывает.
   Действия — те же, что на экранах: запуск идёт через общий запуск
   публикации со своим окном подтверждения. */

interface Command {
  id: string
  group: string
  label: string
  icon: LucideIcon
  /** по чему ещё искать, кроме подписи */
  keywords?: string
  run: () => void
}

const TEXT = localize({
  title: "Команды",
  placeholder: "Раздел, действие или @аккаунт",
  empty: "Ничего не найдено",
  sections: "Разделы",
  actions: "Действия",
  accounts: "Аккаунты",
  launch: "Запустить публикацию",
  stop: "Остановить публикацию",
  checkProxies: "Обновить прокси",
  refreshProfiles: "Обновить профили",
  addAccounts: "Добавить аккаунты",
  notRefreshed: "Профили не обновлены",
} as const)

const ACCOUNTS_SHOWN = 8

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  useHotkey("Mod+K", () => setOpen((v) => !v), { inInputs: true })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent showCloseButton={false} className="top-[20%] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-lg">
        {open ? <Palette onDone={() => setOpen(false)} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function Palette({ onDone }: { onDone: () => void }) {
  const language = useLanguage()
  const [, navigate] = useLocation()
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)
  const accounts = useAccounts().data?.accounts
  const { launch, stop, live } = useCampaignLauncher()

  const commands = useMemo<Command[]>(() => {
    // The catalog resolves labels through the selected language.
    void language
    const openAccount = (username: string) => {
      useAccountsView.getState().setCard(username)
      navigate(sectionPath("accounts"))
    }
    const list: Command[] = [
      ...SECTIONS.map((s) => ({
        id: `go-${s.id}`,
        group: TEXT.sections,
        label: s.title,
        icon: s.icon,
        run: () => navigate(s.path),
      })),
      live
        ? { id: "stop", group: TEXT.actions, label: TEXT.stop, icon: SquareIcon, run: () => void stop() }
        : { id: "launch", group: TEXT.actions, label: TEXT.launch, icon: PlayIcon, run: () => void launch() },
      {
        id: "check-proxies",
        group: TEXT.actions,
        label: TEXT.checkProxies,
        icon: RefreshCwIcon,
        run: () => void checkProxiesNow(),
      },
      {
        id: "refresh-profiles",
        group: TEXT.actions,
        label: TEXT.refreshProfiles,
        icon: RefreshCwIcon,
        run: () => void startProfilesRefresh().catch((error) => notify.error(error, TEXT.notRefreshed)),
      },
      {
        id: "add-accounts",
        group: TEXT.actions,
        label: TEXT.addAccounts,
        icon: PlusIcon,
        run: () => navigate(sectionPath("accounts")),
      },
    ]
    for (const a of accounts ?? []) {
      list.push({
        id: `acc-${a.username}`,
        group: TEXT.accounts,
        label: atUsername(a.username),
        icon: UserRoundIcon,
        keywords: a.region ?? "",
        run: () => openAccount(a.username),
      })
    }
    return list
  }, [accounts, live, launch, stop, navigate, language])

  const shown = useMemo(() => {
    void language
    const q = query.trim().toLowerCase()
    const byName = q.replace(/^@/, "")
    // аккаунтов бывают сотни: без запроса их не показываем, с запросом — первые
    if (!q) return commands.filter((c) => c.group !== TEXT.accounts)
    const hit = commands.filter((c) =>
      c.group === TEXT.accounts
        ? c.label.toLowerCase().includes(byName) || c.keywords?.toLowerCase() === byName
        : c.label.toLowerCase().includes(q)
    )
    const accountHits = hit.filter((c) => c.group === TEXT.accounts).slice(0, ACCOUNTS_SHOWN)
    return [...hit.filter((c) => c.group !== TEXT.accounts), ...accountHits]
  }, [commands, query, language])

  const current = Math.min(active, Math.max(0, shown.length - 1))

  const run = (cmd: Command | undefined) => {
    if (!cmd) return
    onDone()
    cmd.run()
  }

  const move = (delta: number) => {
    if (!shown.length) return
    const next = (current + delta + shown.length) % shown.length
    setActive(next)
    listRef.current?.querySelector<HTMLElement>(`[data-index="${next}"]`)?.scrollIntoView({ block: "nearest" })
  }

  let lastGroup = ""
  return (
    <>
      <DialogTitle className="sr-only">{TEXT.title}</DialogTitle>
      <div className="flex items-center gap-2 border-b px-4">
        <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
        <input
          autoFocus
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setActive(0)
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault()
              move(1)
            } else if (e.key === "ArrowUp") {
              e.preventDefault()
              move(-1)
            } else if (e.key === "Enter") {
              e.preventDefault()
              run(shown[current])
            }
          }}
          placeholder={TEXT.placeholder}
          aria-label={TEXT.placeholder}
          role="combobox"
          aria-expanded
          aria-controls="command-list"
          aria-activedescendant={shown[current] ? `cmd-${shown[current].id}` : undefined}
          className="h-12 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          spellCheck={false}
          autoComplete="off"
        />
        <Kbd>Esc</Kbd>
      </div>
      <div ref={listRef} id="command-list" role="listbox" className="max-h-80 overflow-y-auto p-2">
        {shown.length ? (
          shown.map((cmd, i) => {
            const header = cmd.group !== lastGroup ? cmd.group : null
            lastGroup = cmd.group
            return (
              <div key={cmd.id}>
                {header ? <div className="px-2 pt-2 pb-1 text-xs text-muted-foreground">{header}</div> : null}
                <div
                  id={`cmd-${cmd.id}`}
                  role="option"
                  aria-selected={i === current}
                  data-index={i}
                  onMouseMove={() => setActive(i)}
                  onClick={() => run(cmd)}
                  className={cn(
                    "flex h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm select-none",
                    i === current && "bg-accent"
                  )}
                >
                  <cmd.icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">{cmd.label}</span>
                  {i === current ? <CornerDownLeftIcon className="size-3.5 text-muted-foreground" /> : null}
                </div>
              </div>
            )
          })
        ) : (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">{TEXT.empty}</p>
        )}
      </div>
    </>
  )
}
