import { Fragment, type ComponentType, type ReactNode } from "react"

import { visibleActions, type AccountActionContext, type AccountActionKey } from "./actions"

/* Пункты меню из общего списка (actions.tsx): значок, подпись, черта и
   доступность приходят оттуда, а здесь только разметка. Меню под троеточием и
   меню по правому клику отличаются примитивом, поэтому он и передаётся сюда:
   список у них один и тот же. Панель над выделением собирается из
   visibleActions сама — там кнопки, и вид у них свой. */

/* Общее у DropdownMenuItem и ContextMenuItem: этого пункту списка хватает. */
export interface AccountMenuItemProps {
  children?: ReactNode
  disabled?: boolean
  variant?: "default" | "destructive"
  onClick?: () => void
}

export function AccountActionItems<K extends AccountActionKey>({
  keys,
  ctx,
  run,
  Item,
  Separator,
}: {
  keys: readonly K[]
  ctx: AccountActionContext
  run: (key: K) => void
  Item: ComponentType<AccountMenuItemProps>
  /** черта перед удалением: она есть у пункта, а у кнопки панели её нет */
  Separator: ComponentType
}) {
  return visibleActions(keys, ctx).map((action) => (
    <Fragment key={action.key}>
      {action.separatorBefore ? <Separator /> : null}
      <Item
        disabled={action.disabled(ctx)}
        variant={action.destructive ? "destructive" : "default"}
        onClick={() => run(action.key)}
      >
        <action.icon />
        {action.label(ctx)}
      </Item>
    </Fragment>
  ))
}
