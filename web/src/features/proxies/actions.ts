import {
  CopyIcon,
  GlobeIcon,
  LogInIcon,
  PencilIcon,
  PowerIcon,
  PowerOffIcon,
  RefreshCwIcon,
  SendIcon,
  Trash2Icon,
  type LucideIcon,
} from "lucide-react"

import type { BarAction } from "@/components/selection-bar"

import { isEnabled, type ProxyRow } from "./filter"
import { canRotate, rotateLeft } from "./health"
import {
  NOSHADOW_LABEL,
  PROXIES_LABEL,
  PROXY_ACTION,
  PROXY_BULK,
  rotateWait,
} from "./labels"

export type ProxyActionKey =
  | "enable"
  | "disable"
  | "copy"
  | "edit"
  | "login-on"
  | "login-off"
  | "registration-on"
  | "registration-off"
  | "publish-on"
  | "publish-off"
  | "noshadow"
  | "renew"
  | "rotate"
  | "remove"

// Like accounts/actions: every menu and the selection bar use the same definitions.
export function proxyActions(
  rows: ProxyRow[],
  run: (key: ProxyActionKey) => void,
  {
    elapsed = 0,
    rotateBusy,
  }: { elapsed?: number; rotateBusy?: ReadonlySet<number> } = {}
): BarAction[] {
  if (!rows.length) return []
  const enabled = rows.some(isEnabled)
  const sticky = rows.filter((r) => r.noshadow && r.noshadow.minutes > 0)
  const rotating = rows.filter((r) => r.rotating)
  const busy = rows.some((r) => rotateBusy?.has(r.index))
  const action = (
    key: ProxyActionKey,
    label: string,
    icon: LucideIcon,
    options: Partial<BarAction> = {}
  ): BarAction => ({ key, label, icon, onClick: () => run(key), ...options })

  return [
    ...(enabled ? [action("disable", PROXY_BULK.disable, PowerOffIcon)] : []),
    ...(rows.some((r) => !isEnabled(r))
      ? [action("enable", PROXY_BULK.enable, PowerIcon)]
      : []),
    action("copy", PROXY_BULK.copy, CopyIcon),
    ...(rows.length === 1
      ? [action("edit", PROXY_ACTION.edit, PencilIcon, { disabled: busy })]
      : []),
    action("login-on", PROXY_BULK.loginOn, LogInIcon),
    action("login-off", PROXY_BULK.loginOff, LogInIcon),
    action("registration-on", PROXY_BULK.registrationOn, LogInIcon),
    action("registration-off", PROXY_BULK.registrationOff, LogInIcon),
    action("publish-on", PROXY_BULK.publishOn, SendIcon),
    action("publish-off", PROXY_BULK.publishOff, SendIcon),
    ...(rows.some((r) => r.noshadow)
      ? [action("noshadow", NOSHADOW_LABEL.bulk, GlobeIcon, { disabled: busy })]
      : []),
    ...(sticky.length
      ? [
          action("renew", NOSHADOW_LABEL.renew, RefreshCwIcon, {
            disabled: busy || !sticky.some(isEnabled),
          }),
        ]
      : []),
    ...(rotating.length
      ? [
          action(
            "rotate",
            busy
              ? PROXIES_LABEL.rotating
              : rows.length === 1
                ? rotateWait(rotateLeft(rows[0], elapsed)) ||
                  PROXIES_LABEL.rotate
                : PROXIES_LABEL.rotate,
            RefreshCwIcon,
            {
              disabled:
                busy ||
                !rotating.some((r) => isEnabled(r) && canRotate(r, elapsed)),
            }
          ),
        ]
      : []),
    action("remove", PROXY_BULK.remove, Trash2Icon, {
      disabled: !!rotateBusy?.size,
      destructive: true,
      separatorBefore: true,
    }),
  ]
}
