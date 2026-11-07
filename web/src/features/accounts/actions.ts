import { t } from "@/lib/i18n"
import {
  BanIcon,
  CopyIcon,
  EraserIcon,
  ExternalLinkIcon,
  LogInIcon,
  LogOutIcon,
  PencilIcon,
  SendIcon,
  RefreshCwIcon,
  Trash2Icon,
  UserXIcon,
  type LucideIcon,
} from "lucide-react"

import type { Account } from "@/api/types"

import { ACCOUNT_ACTION, COPY_LABEL } from "./labels"

/* Один список пунктов на все входы экрана: меню строки под троеточием,
   контекстное меню по правому клику и панель над выделением. Значок, подпись
   и условия доступности живут здесь, а вход выбирает только состав и порядок
   (ROW_ACTIONS или SELECTION_ACTIONS) и над чем действует. Третьей копии
   пунктов быть не должно: разошедшаяся копия врёт человеку — пункт он видит,
   а условия у него уже другие. */

export type AccountActionKey =
  | "publish"
  | "refresh"
  | "open"
  | "copy"
  | "login"
  | "clearSession"
  | "logout"
  | "edit"
  | "purge"
  | "disable"
  | "remove"

/* Состав и порядок пунктов у входа свой, и это не косметика: открыть в TikTok
   осмысленно для одного аккаунта, а вход — дело выделения, где есть аккаунты
   без сохранённого входа. Строка вход не показывает: рядом с логином у неё
   для этого стоит кнопка. Изменить — тоже дело одного аккаунта: форма правки
   несёт один пароль и один логин, а не общую замену на выделение. */
export const ROW_ACTIONS = [
  "publish",
  "refresh",
  "open",
  "copy",
  "edit",
  "purge",
  "clearSession",
  "logout",
  "disable",
  "remove",
] as const
export const SELECTION_ACTIONS = [
  "publish",
  "refresh",
  "copy",
  "login",
  "purge",
  "clearSession",
  "logout",
  "disable",
  "remove",
] as const

export type SelectionActionKey = (typeof SELECTION_ACTIONS)[number]

/* Что знает пункт о своём наборе аккаунтов. Занятость считается только у
   строки: панель над выделением гасит кнопки лишь на время публикации, а
   работа с одним аккаунтом другим не мешает. */
export interface AccountActionContext {
  /** сколько аккаунтов затронуто */
  count: number
  /** среди них есть без сохранённого входа */
  pending: boolean
  /** среди них есть со входом */
  session: boolean
  /** идёт публикация: менять аккаунты нельзя, сервер такие запросы отклоняет */
  locked: boolean
  /** этими аккаунтами сейчас заняты: вход, чистка, профиль, публикация */
  busy: boolean
}

/** Контекст по набору аккаунтов: у строки — она одна, у выделения — все
    выбранные, в том числе скрытые срезом или поиском. */
export function actionContext(
  accounts: Account[],
  flags: { locked?: boolean; busy?: boolean } = {}
): AccountActionContext {
  return {
    count: accounts.length,
    pending: accounts.some((a) => !a.has_session),
    session: accounts.some((a) => a.has_session),
    locked: !!flags.locked,
    busy: !!flags.busy,
  }
}

export interface AccountAction<K extends AccountActionKey = AccountActionKey> {
  key: K
  icon: LucideIcon
  /** подпись: у копирования она зависит от числа аккаунтов */
  label: (ctx: AccountActionContext) => string
  /** разрушительное действие — красным: и пунктом в меню, и кнопкой на панели */
  destructive?: boolean
  /** перед пунктом черта: удаление отделено от остальной работы */
  separatorBefore?: boolean
  /* Пункт, неприменимый к этому набору, не показываем вовсе: серое «нельзя»
     человек читает как «сейчас нельзя», а не как «не про этот аккаунт». */
  visible: (ctx: AccountActionContext) => boolean
  disabled: (ctx: AccountActionContext) => boolean
}

export const ACCOUNT_ACTIONS: AccountAction[] = [
  {
    key: "publish",
    icon: SendIcon,
    label: () => ACCOUNT_ACTION.publish,
    visible: () => true,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
  {
    key: "refresh",
    icon: RefreshCwIcon,
    label: () => ACCOUNT_ACTION.refresh,
    visible: () => true,
    // профиль читается анонимно и никому не мешает — доступен и у занятого аккаунта
    disabled: () => false,
  },
  {
    key: "open",
    icon: ExternalLinkIcon,
    label: () => ACCOUNT_ACTION.open,
    // открывать осмысленно один аккаунт: в SELECTION_ACTIONS этого пункта нет
    visible: () => true,
    disabled: () => false,
  },
  {
    key: "copy",
    icon: CopyIcon,
    /* Один пункт на любое число аккаунтов: выделен один — подпись та же, что
       у него в меню строки. В буфер идут все выделенные, а не только видимые
       строки: счётчик на панели называет ровно их, и обещать больше, чем
       копируешь, нельзя. */
    label: (ctx) => (ctx.count > 1 ? COPY_LABEL.many : COPY_LABEL.one),
    visible: () => true,
    // юзернеймы копируются и у занятых аккаунтов: в буфер, не в TikTok
    disabled: () => false,
  },
  {
    key: "login",
    icon: LogInIcon,
    label: () => ACCOUNT_ACTION.login,
    // входить есть куда, только если в наборе есть аккаунт без сохранённого входа
    visible: (ctx) => ctx.pending,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
  {
    key: "edit",
    icon: PencilIcon,
    label: () => ACCOUNT_ACTION.edit,
    // правка одного аккаунта: занятого (вход, чистка, публикация) не трогаем
    visible: () => true,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
  {
    key: "purge",
    icon: EraserIcon,
    label: () => ACCOUNT_ACTION.purge,
    // на аккаунте без входа чистить нечего
    visible: (ctx) => ctx.session,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
  {
    key: "clearSession",
    icon: UserXIcon,
    label: () => ACCOUNT_ACTION.clearSession,
    // Забывает только локально сохранённый вход; у TikTok сессия остаётся.
    visible: (ctx) => ctx.session,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
  {
    key: "logout",
    icon: LogOutIcon,
    label: () => ACCOUNT_ACTION.logout,
    // Настоящий выход у TikTok (modules/login.remote_logout) — не только локально.
    visible: (ctx) => ctx.session,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
  {
    key: "disable",
    icon: BanIcon,
    label: () => ACCOUNT_ACTION.disable,
    // ручной перевод в отключённые — на случай, когда автоотключения нет
    // (например, TikTok отвечает «такого юзернейма нет»)
    visible: () => true,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
  {
    key: "remove",
    icon: Trash2Icon,
    label: () => ACCOUNT_ACTION.delete,
    destructive: true,
    separatorBefore: true,
    visible: () => true,
    disabled: (ctx) => ctx.locked || ctx.busy,
  },
]

/** Пункт по ключу: им собирается и кнопка, которая живёт вне меню (вход в строке). */
export function accountAction<K extends AccountActionKey>(
  key: K
): AccountAction<K> {
  const found = ACCOUNT_ACTIONS.find((a) => a.key === key)
  if (!found) throw new Error(t("неизвестный пункт списка аккаунтов: {0}", [key]))
  return found as AccountAction<K>
}

/** Пункты этого входа по порядку списка, применимые к набору. */
export function visibleActions<K extends AccountActionKey>(
  keys: readonly K[],
  ctx: AccountActionContext
): AccountAction<K>[] {
  return keys.map((key) => accountAction(key)).filter((a) => a.visible(ctx))
}

/** Что делает каждый пункт над строкой. Вход в ROW_ACTIONS не входит — его
    зовёт кнопка рядом с логином, — но обработчик у строки для него есть. */
export type AccountRowActions = Record<
  AccountActionKey,
  (username: string) => void
>

/** Что делает каждый пункт над выделением: панель и меню по правому клику. */
export type SelectionActions = Record<SelectionActionKey, () => void>

/** Правый клик по выделенной строке: меню действует на всё выделение, как панель. */
export interface SelectionTarget {
  ctx: AccountActionContext
  run: (key: SelectionActionKey) => void
}
