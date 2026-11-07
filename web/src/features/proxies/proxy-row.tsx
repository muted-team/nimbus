import { t, useLanguage } from "@/lib/i18n"
import { userMessage } from "@/api/client"
import { Fragment, useState, type ComponentType, type ReactNode } from "react"
import { EllipsisIcon, PencilIcon, PowerIcon, RefreshCwIcon, Trash2Icon } from "lucide-react"

import { Flag } from "@/components/flag"
import type { BarAction } from "@/components/selection-bar"
import { StatusDot, type Tone } from "@/components/status"
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
import { Switch } from "@/components/ui/switch"
import { usePressOrigin } from "@/hooks/use-press-origin"
import { fmtDec, fmtInt } from "@/lib/format"
import type { PickMode } from "@/lib/selection"
import { cn } from "@/lib/utils"

import { CELL } from "./columns"
import { isEnabled, type ProxyRow } from "./filter"
import { canRotate, rotateLeft } from "./health"
import { checkedAgo, NOSHADOW_LABEL, noshadowMode, PROXIES_LABEL, PROXY_ACTION, rotateWait, STATE_WORD } from "./labels"

/* Строка настоящей `<table>` (не сетки — виртуализации здесь нет, строк
   десятки, не сотни): адрес и состояние, страна, числа, группы входа и публикации,
   действия. Ключ строки — её номер в исходном списке (row.index), не адрес:
   у пачки от одного провайдера адрес совпадает, а смена IP, правка и отметки
   идут по номеру. Отключённая строка приглушена — тот же приём, что у
   отключённых аккаунтов, — но остаётся на месте и доступна для правки.

   Выравнивание и видимость каждой ячейки — из columns.ts (CELL): тот же
   класс стоит и у заголовка колонки, поэтому разойтись они не могут. */

const DOT_TONE: Record<ProxyRow["state"], Tone> = {
  ok: "ok",
  dead: "bad",
  unknown: "neutral",
  checking: "live",
}

const TD = "px-3 py-2"

export interface ProxyRowActions {
  edit: (index: number) => void
  remove: (index: number) => void
  rotate: (index: number) => void
  /** noshadow с липким IP: новая сессия — новый IP */
  renew: (index: number) => void
  toggleEnabled: (index: number) => void
  toggleLogin: (index: number, checked: boolean) => void
  togglePublish: (index: number, checked: boolean) => void
}

/* Общее у DropdownMenuItem и ContextMenuItem: этого пункту списка хватает —
   тот же приём, что у списка аккаунтов (action-items.tsx). */
interface ProxyMenuItemProps {
  children?: ReactNode
  variant?: "default" | "destructive"
  onClick?: () => void
  disabled?: boolean
}

/* Смена IP — в меню строки, а не отдельной кнопкой в таблице: с подписью
   («Сменить IP» / «смена через 30 с») она была то шире, то уже соседних
   строк — на широких таблицах последняя колонка обрезалась краем панели. */
function ActionItems({
  row,
  actions,
  elapsed,
  rotateBusy,
  Item,
  Separator,
}: {
  row: ProxyRow
  actions: ProxyRowActions
  elapsed: number
  rotateBusy: boolean
  Item: ComponentType<ProxyMenuItemProps>
  Separator: ComponentType
}) {
  useLanguage()
  const enabled = isEnabled(row)
  const wait = rotateWait(rotateLeft(row, elapsed))
  return (
    <>
      <Item onClick={() => actions.edit(row.index)}>
        <PencilIcon />
        {PROXY_ACTION.edit}
      </Item>
      <Item onClick={() => actions.toggleEnabled(row.index)}>
        <PowerIcon />
        {enabled ? PROXY_ACTION.disable : PROXY_ACTION.enable}
      </Item>
      {row.noshadow && row.noshadow.minutes > 0 ? (
        <Item disabled={!enabled} onClick={() => actions.renew(row.index)}>
          <RefreshCwIcon />
          {NOSHADOW_LABEL.renew}
        </Item>
      ) : null}
      {row.rotating ? (
        <Item
          disabled={!enabled || !canRotate(row, elapsed) || rotateBusy}
          onClick={() => actions.rotate(row.index)}
        >
          {rotateBusy ? <Spinner className="size-3.5" /> : <RefreshCwIcon />}
          {rotateBusy ? PROXIES_LABEL.rotating : wait || PROXIES_LABEL.rotate}
        </Item>
      ) : null}
      <Separator />
      <Item variant="destructive" onClick={() => actions.remove(row.index)}>
        <Trash2Icon />
        {PROXY_ACTION.remove}
      </Item>
    </>
  )
}

/* Выбор — как у аккаунтов: флажок, клик по строке, Ctrl и Shift. Своей
   карточки у прокси нет, поэтому простой клик по строке тоже выбирает;
   кнопки, тумблеры и меню в строке выбор не трогают.

   Правый клик — тоже как у аккаунтов: по строке из выбора нескольких
   открывается меню над всем выбором (те же действия, что на панели снизу),
   по любой другой — выбор переходит на неё и меню этой строки. */
export function ProxyTableRow({
  row,
  elapsed,
  rotateBusy,
  actions,
  selected,
  onPick,
  selectionCount,
  bulk,
}: {
  row: ProxyRow
  /** секунд с момента снимка — отсчёт смены IP идёт от него */
  elapsed: number
  /** смена IP идёт именно у этой строки */
  rotateBusy: boolean
  actions: ProxyRowActions
  selected: boolean
  onPick: (index: number, mode: PickMode) => void
  /** сколько строк выбрано всего */
  selectionCount: number
  /** действия над всем выбором — для меню по правому клику */
  bulk: BarAction[]
}) {
  useLanguage()
  const enabled = isEnabled(row)
  const press = usePressOrigin()
  const [overSelection, setOverSelection] = useState(false)
  return (
    <ContextMenu>
      <ContextMenuTrigger
        render={
          <tr
            aria-selected={selected}
            data-selected={selected || undefined}
            onPointerDown={press.onPointerDown}
            onContextMenu={() => {
              const groupMenu = selected && selectionCount > 1
              setOverSelection(groupMenu)
              // уже выбранную одну не трогаем: повторный «только эта» снял бы выбор
              if (!groupMenu && !selected) onPick(row.index, "solo")
            }}
            onClick={(e: React.MouseEvent) => {
              // щелчок, начатый в меню над строкой, — это выбор пункта, а не строки
              if (!press.take(e)) return
              if ((e.target as HTMLElement).closest("button, a, input, [role=checkbox], [role=switch]")) return
              onPick(row.index, e.shiftKey ? "range" : "toggle")
            }}
            onMouseDown={(e: React.MouseEvent) => {
              if (e.shiftKey || e.ctrlKey || e.metaKey) e.preventDefault()
            }}
            className={cn(
              "group/row h-10 cursor-pointer border-b transition-colors select-none hover:bg-muted/40",
              "data-[selected]:bg-primary/10 data-[selected]:shadow-[inset_2px_0_0_var(--primary)]",
              !enabled && "opacity-60"
            )}
          />
        }
      >
        <td className={cn(TD, "w-8 pl-4 md:pl-6")}>
          <Checkbox
            checked={selected}
            aria-label={PROXIES_LABEL.pick(row.proxy)}
            onClick={(e) => {
              e.preventDefault()
              onPick(row.index, e.shiftKey ? "range" : "toggle")
            }}
          />
        </td>
        <td className={cn(TD, CELL.index)}>{row.index + 1}</td>
        <td className={cn(TD, CELL.proxy)}>
          {/* на телефоне остальные колонки прячутся (sm:table-cell), и без
              потолка длинный адрес выталкивал колонку действий за край экрана;
              текст остаётся выделяемым целиком — обрезка только визуальная */}
          <span className="block max-w-28 truncate font-mono text-xs select-text sm:max-w-none">
            {row.proxy}
          </span>
          {row.noshadow ? (
            <span className="hidden text-xs text-muted-foreground sm:block">
              {noshadowMode(row.noshadow.country, row.noshadow.minutes)}
            </span>
          ) : null}
        </td>
        <td className={cn(TD, CELL.country)}>
          <div className="flex justify-center">
            <Flag code={row.country} />
          </div>
        </td>
        <td className={cn(TD, "text-xs text-muted-foreground", CELL.scheme)}>{row.scheme || "—"}</td>
        <td className={cn(TD, CELL.state)}>
          <div className="flex flex-col gap-0.5">
            <span className="inline-flex items-center gap-2">
              {row.state === "checking" ? (
                <Spinner className="size-3.5 text-muted-foreground" />
              ) : (
                <StatusDot tone={DOT_TONE[row.state]} />
              )}
              <span className="text-xs text-muted-foreground">{STATE_WORD[row.state]}</span>
            </span>
            {row.state === "dead" && row.error ? (
              // на телефоне остальные колонки уже прячутся (sm:table-cell) — причина
              // отказа туда же: короткого «не отвечает» хватает, а длинный текст
              // вытеснял единственную оставшуюся колонку действий за край экрана
              <span className="hidden max-w-40 truncate text-xs text-destructive sm:block">
                {userMessage(row.error)}
              </span>
            ) : row.state === "ok" && row.org ? (
              // оператор выхода: по нему видно, домашний это адрес или нет
              <span className="hidden max-w-40 truncate text-xs text-muted-foreground sm:block" title={row.org}>
                {row.org}
              </span>
            ) : null}
          </div>
        </td>
        <td className={cn(TD, "text-xs text-muted-foreground", CELL.ping)}>
          {row.ping != null ? t("{0} мс", [fmtInt(row.ping)]) : "—"}
        </td>
        <td className={cn(TD, "text-xs text-muted-foreground", CELL.ms)}>
          {row.ms != null ? t("{0} с", [fmtDec(row.ms / 1000)]) : "—"}
        </td>
        <td className={cn(TD, "text-xs text-muted-foreground", CELL.busy)}>
          {row.busy ? fmtInt(row.busy) : "—"}
        </td>
        <td className={cn(TD, "text-xs text-muted-foreground", CELL.checked)}>{checkedAgo(row.checked_at)}</td>
        <td className={cn(TD, CELL.login)}>
          <div className="flex justify-center">
            <Switch
              size="sm"
              checked={!!row.login}
              disabled={!enabled}
              onCheckedChange={(checked) => actions.toggleLogin(row.index, checked)}
              aria-label={t("Вход: {0}", [row.proxy])}
            />
          </div>
        </td>
        <td className={cn(TD, CELL.publish)}>
          <div className="flex justify-center">
            <Switch
              size="sm"
              checked={!!row.publish}
              disabled={!enabled}
              onCheckedChange={(checked) => actions.togglePublish(row.index, checked)}
              aria-label={t("Публикация: {0}", [row.proxy])}
            />
          </div>
        </td>
        <td className={cn(TD, "pr-4 md:pr-6 group-hover/row:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))] group-data-[selected]/row:bg-[color-mix(in_oklch,var(--primary)_10%,var(--background))]", CELL.actions)}>
          <div className="flex items-center justify-end">
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="ghost" size="icon-sm" aria-label={PROXY_ACTION.more} />}
              >
                {rotateBusy ? <Spinner className="size-3.5" /> : <EllipsisIcon />}
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-44">
                <ActionItems
                  row={row}
                  actions={actions}
                  elapsed={elapsed}
                  rotateBusy={rotateBusy}
                  Item={DropdownMenuItem}
                  Separator={DropdownMenuSeparator}
                />
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </td>
      </ContextMenuTrigger>
      <ContextMenuContent className="w-auto min-w-44">
        {overSelection ? (
          bulk.map((a) => (
            <Fragment key={a.key}>
              {a.separatorBefore ? <ContextMenuSeparator /> : null}
              <ContextMenuItem
                disabled={a.disabled}
                variant={a.destructive ? "destructive" : "default"}
                onClick={a.onClick}
              >
                <a.icon />
                {a.label}
              </ContextMenuItem>
            </Fragment>
          ))
        ) : (
          <ActionItems
            row={row}
            actions={actions}
            elapsed={elapsed}
            rotateBusy={rotateBusy}
            Item={ContextMenuItem}
            Separator={ContextMenuSeparator}
          />
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
}
