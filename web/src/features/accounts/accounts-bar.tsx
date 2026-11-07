import { useLanguage } from "@/lib/i18n"
import { SquareIcon } from "lucide-react"

import { SelectionBar } from "@/components/selection-bar"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"

import {
  SELECTION_ACTIONS,
  visibleActions,
  type AccountActionContext,
  type SelectionActionKey,
  type SelectionActions,
} from "./actions"
import { runProgressText, useAccountsRun } from "./accounts-run"
import { SELECT_LABEL } from "./labels"

/* Панель поверх списка аккаунтов: пока идёт прогон — его прогресс и
   «Остановить», иначе — действия над выделением (общая SelectionBar).

   Действия берут выделение целиком, а не видимые строки: выделение переживает
   поиск (смена среза его сбрасывает), и панель обязана обещать ровно то, что
   делает. Пункты собираются из общего списка (actions.ts): тот же список
   рисует меню строки и меню по правому клику, и разойтись им негде. Первыми
   кнопками — три частых действия, остальное в «Ещё». */

const MAIN: readonly SelectionActionKey[] = ["publish", "refresh", "copy"]
const ORDER = [...MAIN, ...SELECTION_ACTIONS.filter((k) => !MAIN.includes(k))]

export function AccountsBar({
  ctx,
  actions,
  onClear,
}: {
  ctx: AccountActionContext
  actions: SelectionActions
  onClear: () => void
}) {
  useLanguage()
  const run = useAccountsRun((s) => s.run)
  const requestStop = useAccountsRun((s) => s.requestStop)

  const items = ctx.count
    ? visibleActions(ORDER, ctx).map((a) => ({
        key: a.key,
        label: a.label(ctx),
        icon: a.icon,
        disabled: a.disabled(ctx),
        destructive: a.destructive,
        separatorBefore: a.separatorBefore,
        onClick: actions[a.key],
      }))
    : []

  /* Прогресс и действия над выделением видны вместе: пока идёт вход в одни
     аккаунты, можно выбрать другие и отправить их следом. */
  return (
    <SelectionBar count={ctx.count} actions={items} main={MAIN.length} onClear={onClear}>
      {run ? (
        <div className="flex w-full items-center justify-center gap-2">
          <Spinner className="size-4 text-primary" />
          <span className="px-1 text-sm text-muted-foreground tabular">{runProgressText(run)}</span>
          <Button variant="outline" size="sm" onClick={requestStop} disabled={run.stopping}>
            <SquareIcon />
            {run.stopping ? SELECT_LABEL.stopping : SELECT_LABEL.stop}
          </Button>
        </div>
      ) : null}
    </SelectionBar>
  )
}
