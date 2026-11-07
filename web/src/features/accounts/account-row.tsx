import { useLanguage } from "@/lib/i18n"
import { memo, useState } from "react"
import { EllipsisIcon, EyeIcon, EyeOffIcon, HeartIcon, UserRoundIcon, UsersRoundIcon, VideoIcon, type LucideIcon } from "lucide-react"

import type { Account, StudioCountersMap } from "@/api/types"
import { Flag } from "@/components/flag"
import { toneText } from "@/components/status"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Spinner } from "@/components/ui/spinner"
import { usePressOrigin } from "@/hooks/use-press-origin"
import { fmtAgo, fmtCompact } from "@/lib/format"
import { cn } from "@/lib/utils"

import { AccountActionItems } from "./action-items"
import { accountAction, actionContext, ROW_ACTIONS, SELECTION_ACTIONS, type AccountRowActions, type SelectionTarget } from "./actions"
import type { Column, ColumnKey } from "./columns"
import { ACCOUNT_ACTION, COLUMN_LABEL, SELECT_LABEL } from "./labels"
import { rowNumbers, type RowNumbers } from "./studio"
import { atUsername } from "./username"

/* Вход в строке — тот же пункт общего списка, что и в панели над выделением:
   и подпись, и значок, и доступность берутся из actions.tsx. */
const LOGIN = accountAction("login")

/* Строка таблицы: флажок выбора, аватар с логином, числа по видимым колонкам,
   действия справа. Клик по строке открывает карточку аккаунта; выбор — флажком,
   Ctrl и Shift по строке тоже выбирают, как в проводнике. Правый клик
   работает с тем аккаунтом, по которому кликнули: строка вне выделения (или
   выделение — это она одна) — её меню; строка из выделения нескольких — меню
   над всем выделением, как нижняя панель.

   У логина из меток только тень, и то пока своей колонки у неё нет:
   галочка, замок, способ входа и посетители — в карточке. Пять значков без
   подписей у логина читались как шум. Высота строки одна на весь список —
   40 px; на телефоне под логином строка с числами, и строка выше. */

export interface RowHandlers {
  actions: AccountRowActions
  /** клик по строке без Ctrl и Shift — карточка аккаунта */
  onOpen: (username: string) => void
  /** флажок, Ctrl или Shift по строке */
  onPick: (username: string, mode: "toggle" | "range") => void
  /** правый клик по невыделенной строке: выделение переходит на неё */
  onContextSelect: (username: string) => void
}

export const AccountRow = memo(function AccountRow({
  account,
  avatar,
  counters,
  busy,
  locked,
  selected,
  columns,
  template,
  handlers,
  selection,
}: {
  account: Account
  /** готовая картинка из отдельного запроса аватарок */
  avatar?: string
  /** числа студии по аккаунтам: стоят выше чисел профиля */
  counters?: StudioCountersMap
  /** этим аккаунтом сейчас занимаются: вход, чистка, профиль, публикация */
  busy: boolean
  /** идёт публикация: менять аккаунты нельзя, сервер такие запросы отклоняет */
  locked: boolean
  selected: boolean
  columns: Column[]
  /** шаблон сетки — общий с шапкой */
  template: string
  handlers: RowHandlers
  /** правый клик по выделенной строке: меню действует на всё выделение */
  selection: SelectionTarget
}) {
  const p = account.profile
  const shadow = p?.posts?.shadow
  const numbers = rowNumbers(account, counters)
  const rowCtx = actionContext([account], { locked, busy })
  const loginLabel = LOGIN.label(rowCtx)
  const shadowColumn = columns.some((c) => c.key === "shadow")
  const { actions } = handlers
  const u = account.username

  /* Какое меню откроет правый клик, решается в его момент: групповое — только
     когда выделено больше одного и кликнули по строке из этого выделения. */
  const [overSelection, setOverSelection] = useState(false)
  const press = usePressOrigin()

  const cell: Record<ColumnKey, React.ReactNode> = {
    region: <Flag code={account.region} />,
    followers: <Num value={numbers.followers} />,
    likes: <Num value={p?.likes} />,
    views: <Num value={p?.posts?.views} />,
    posts: <Num value={numbers.posts} />,
    shadow: <Num value={shadow} tone={shadow ? "warn" : undefined} />,
    fetched: <span className="truncate text-xs text-muted-foreground tabular">{fmtAgo(p?.fetched_at)}</span>,
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger
        role="row"
        aria-selected={selected}
        data-selected={selected || undefined}
        onPointerDown={press.onPointerDown}
        onClick={(e: React.MouseEvent) => {
          // щелчок, начатый в меню над строкой, — это выбор пункта, а не строки
          if (!press.take(e)) return
          if ((e.target as HTMLElement).closest("button, a, input, textarea, [role=checkbox]")) return
          if (e.shiftKey) handlers.onPick(u, "range")
          else if (e.ctrlKey || e.metaKey) handlers.onPick(u, "toggle")
          else handlers.onOpen(u)
        }}
        // Shift и Ctrl — это выделение строк: без отмены браузер тянет за
        // собой выделение текста, и строка выглядит залитой синим
        onMouseDown={(e: React.MouseEvent) => {
          if (e.shiftKey || e.ctrlKey || e.metaKey) e.preventDefault()
        }}
        onContextMenu={() => {
          const groupMenu = selected && selection.ctx.count > 1
          setOverSelection(groupMenu)
          // уже выбранную одну не трогаем: повторный «только эта» снял бы выбор
          if (!groupMenu && !selected) handlers.onContextSelect(u)
        }}
        style={{ gridTemplateColumns: template }}
        className={cn(
          "grid w-full cursor-pointer items-center gap-x-3 border-b px-4 md:px-6 text-row transition-colors select-none",
          "min-h-10 py-1 md:h-10 md:py-0",
          "hover:bg-muted/40",
          // выделенную строку метим ещё и полосой слева: на длинном списке одна
          // заливка теряется, особенно когда выделено подряд несколько
          "data-[selected]:bg-primary/10 data-[selected]:shadow-[inset_2px_0_0_var(--primary)] data-[selected]:hover:bg-primary/15"
        )}
      >
        <div className="flex items-center" role="gridcell">
          <Checkbox
            checked={selected}
            aria-label={SELECT_LABEL.pick(atUsername(u))}
            onClick={(e) => {
              e.stopPropagation()
              e.preventDefault()
              handlers.onPick(u, e.shiftKey ? "range" : "toggle")
            }}
          />
        </div>

        {/* аккаунт */}
        <div className="flex min-w-0 items-center gap-2" role="gridcell">
          <Avatar className="size-7 shrink-0">
            {avatar ? <AvatarImage src={avatar} alt="" /> : null}
            <AvatarFallback>
              <UserRoundIcon className="size-3.5 text-muted-foreground" />
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate font-medium select-text">{atUsername(u)}</span>
              {/* аккаунтом заняты — спиннер рядом с логином: аватар остаётся,
                  строку по-прежнему узнаёшь в лицо */}
              {busy ? <Spinner className="size-3.5 shrink-0 text-primary" /> : null}
              {shadow && !shadowColumn ? (
                <span className={cn("inline-flex shrink-0 items-center gap-1 text-xs", toneText.warn)}>
                  <EyeOffIcon className="size-3.5" aria-label={COLUMN_LABEL.shadow} />
                  <span className="tabular">{fmtCompact(shadow)}</span>
                </span>
              ) : null}
            </div>
            {columns.length ? null : <NarrowStats account={account} numbers={numbers} />}
          </div>
        </div>

        {columns.map((c) => (
          <div
            key={c.key}
            role="gridcell"
            className={cn("flex min-w-0 items-center", c.align === "end" ? "justify-end" : "justify-center")}
          >
            {cell[c.key]}
          </div>
        ))}

        {/* действия */}
        <div className="flex items-center justify-end gap-1" role="gridcell">
          {/* Нет сохранённого входа — это дело, а не метка: кнопка вместо
              плашки «Без входа». На телефоне кнопка остаётся значком. */}
          {!account.has_session ? (
            <Button
              variant="outline"
              size="sm"
              aria-label={loginLabel}
              disabled={LOGIN.disabled(rowCtx)}
              onClick={() => actions.login(u)}
            >
              <LOGIN.icon />
              <span className="hidden md:inline">{loginLabel}</span>
            </Button>
          ) : null}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={ACCOUNT_ACTION.more} />}>
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-44">
              <AccountActionItems
                keys={ROW_ACTIONS}
                ctx={rowCtx}
                run={(key) => actions[key](u)}
                Item={DropdownMenuItem}
                Separator={DropdownMenuSeparator}
              />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-auto min-w-44">
        {overSelection ? (
          <AccountActionItems
            keys={SELECTION_ACTIONS}
            ctx={selection.ctx}
            run={selection.run}
            Item={ContextMenuItem}
            Separator={ContextMenuSeparator}
          />
        ) : (
          <AccountActionItems
            keys={ROW_ACTIONS}
            ctx={rowCtx}
            run={(key) => actions[key](u)}
            Item={ContextMenuItem}
            Separator={ContextMenuSeparator}
          />
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
})

/** Ячейка с числом: прочерк вместо пустоты. Ноль и «неизвестно» одинаково
    приглушены: столбик из нулей не перетягивает взгляд с настоящих чисел. */
function Num({ value, tone }: { value: number | null | undefined; tone?: "warn" }) {
  useLanguage()
  const blank = value == null || value === 0
  return (
    <span className={cn("truncate tabular", blank ? "text-muted-foreground" : tone ? toneText.warn : undefined)}>
      {fmtCompact(value)}
    </span>
  )
}

/* Числа под логином — для телефона, где колонок нет вовсе. Строка есть всегда,
   даже когда профиль не загружен: одинаковая высота строк важнее. */
function NarrowStats({ account, numbers }: { account: Account; numbers: RowNumbers }) {
  useLanguage()
  const p = account.profile
  return (
    <div className="flex items-center gap-x-3 text-xs text-muted-foreground">
      <Pair icon={UsersRoundIcon} label={COLUMN_LABEL.followers} value={numbers.followers} />
      <Pair icon={HeartIcon} label={COLUMN_LABEL.likes} value={p?.likes} />
      <Pair icon={EyeIcon} label={COLUMN_LABEL.views} value={p?.posts?.views} />
      <Pair icon={VideoIcon} label={COLUMN_LABEL.posts} value={numbers.posts} />
    </div>
  )
}

function Pair({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number | null | undefined }) {
  useLanguage()
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      <Icon className="size-3.5" aria-label={label} />
      <span className="tabular">{fmtCompact(value)}</span>
    </span>
  )
}
