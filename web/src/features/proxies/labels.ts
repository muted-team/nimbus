import { localize, t } from "@/lib/i18n"
import { count, fmtAgo, fmtInt, sentence } from "@/lib/format"

import type { Capacity } from "./capacity"
import type { ProxiesFilter, SortKey } from "./filter"
import { serverNumber } from "./health"

/* Подписи и тексты экрана прокси — в одном месте. */

export const ADDR: [string, string, string] = localize(["адрес", "адреса", "адресов"])

export const ACCOUNT: [string, string, string] = localize(["аккаунт", "аккаунта", "аккаунтов"])

export const PROXIES_LABEL = localize({
  use: "Использовать",
  list: "Список",
  search: "Поиск по адресу",
  filters: "Срез прокси",
  add: "Добавить",
  placeholder: "login:pass@host:port",
  // «Обновить», а не «Проверить»: то же слово, что на остальных экранах, —
  // одно действие должно называться одинаково во всей программе
  check: "Обновить",
  checking: "Обновляем…",
  checkPanel: "Проверка",
  rotate: "Сменить IP",
  /** смена IP ждёт провайдера до полуминуты — кнопка об этом говорит */
  rotating: "Меняю IP…",
  /** вердикта ещё не было — так и говорим, а не «0 мс» */
  unchecked: "ещё не проверялся",
  /** отметку проверки не прочитать — говорим об этом, а не «NaN дн назад» */
  unreadable: "время проверки неизвестно",
  removeDead: "Удалить мёртвые",
  pick: (addr: string) => t("Выбрать {0}", [addr]),
  pickAll: "Выбрать все",
  pickNone: "Снять выделение",
} as const)

/** Действия над выбранными прокси — панель снизу, как у аккаунтов. */
export const PROXY_BULK = localize({
  enable: "Включить",
  disable: "Отключить",
  copy: "Скопировать",
  loginOn: "Отметить для входа",
  loginOff: "Снять с входа",
  publishOn: "Отметить для публикации",
  publishOff: "Снять с публикации",
  remove: "Удалить",
} as const)

/* Порядок срезов — одно правило с аккаунтами: срез по умолчанию первым,
   дальше рабочие, в конце — те, с которыми надо что-то делать. */
export const FILTER_LABEL: Record<ProxiesFilter, string> = localize({
  all: "Все",
  alive: "Живые",
  unchecked: "Не проверены",
  dead: "Мёртвые",
})

export const EMPTY_LABEL = localize({
  none: "Прокси не добавлены",
  notFound: "Ничего не найдено",
  emptySlice: "В этом срезе пусто",
  clearSearch: "Очистить поиск",
} as const)

/** Заголовки колонок таблицы: сортируемые — по ключу сортировки, остальные —
    отдельным словом (действия и переключатель своих ключей сортировки не несут). */
export const COLUMN_LABEL: Record<SortKey, string> & {
  scheme: string
  state: string
  login: string
  publish: string
  more: string
} = localize({
  index: "№",
  proxy: "Адрес",
  country: "Страна",
  ping: "Пинг",
  ms: "Ответ",
  busy: "Занятость",
  checked_at: "Проверена",
  scheme: "Тип",
  state: "Состояние",
  login: "Вход",
  publish: "Публикация",
  more: "Ещё",
})

/** Слово рядом с точкой состояния — короткое, без «проверено»: заголовок
    колонки уже говорит «Состояние». Причина отказа остаётся подсказкой при
    наведении, а не текстом в ячейке. */
export const STATE_WORD = localize({
  ok: "отвечает",
  dead: "не отвечает",
  checking: "проверяю",
  unknown: "не проверен",
} as const)

/** Подсказки про обязательные группы: пул никогда не подставляет строку из
    общего списка, потому что её IP может быть предназначен для другого дела. */
export function loginHint(marked: number): string {
  return marked > 0
    ? t("Вход идёт только через отмеченные ({0}).", [marked])
    : t("Для входа ничего не выбрано — вход будет остановлен.")
}

export function publishHint(marked: number): string {
  return marked > 0
    ? t("Публикация идёт только через отмеченные ({0}).", [marked])
    : t("Для публикации ничего не выбрано — публикация будет остановлена.")
}

export const PROXY_ACTION = localize({
  edit: "Править",
  remove: "Удалить",
  enable: "Включить",
  disable: "Отключить",
  more: "Ещё",
} as const)

export const PROXY_CONFIRM = localize({
  deleteOne: (addr: string) => t("Удалить прокси {0}?", [addr]),
  deleteDesc: "Строку убирает список безвозвратно.",
  deleteYes: "Удалить",
  deleteDead: (n: number) => t("Удалить мёртвые: {0}?", [count(n, ADDR)]),
  deleteMany: (n: number) => t("Удалить выбранные: {0}?", [count(n, ADDR)]),
} as const)

export const PROXY_EDIT_LABEL = localize({
  title: (addr: string) => t("Правка: {0}", [addr]),
  /** строку не разобрать по полям — правим её одну целиком */
  line: "Строка (не разобралась по полям — правьте как есть)",
  brokenHint: "Эта строка не в обычном виде: показана как есть, без разбора по полям.",
  scheme: "Протокол",
  host: "Хост",
  port: "Порт",
  login: "Логин",
  password: "Пароль",
  rotateUrl: "Ссылка смены IP",
  rotateUrlPlaceholder: "необязательно",
  save: "Сохранить",
  saving: "Сохраняем…",
  cancel: "Отмена",
} as const)

export const PROXY_ADD_LABEL = localize({
  title: "Добавить прокси",
  placeholder: "login:pass@host:port, по одному в строке",
  add: "Добавить",
  adding: "Добавляем…",
  close: "Закрыть",
} as const)

/* noshadow: генератор строк и правка выбранных (noshadow.ts). Режим строки
   подписан так, как его понимает человек, а не суффиксами логина. */
export const NOSHADOW_LABEL = localize({
  open: "Собрать noshadow",
  generateTitle: "Прокси noshadow",
  editTitle: (n: number) => t("noshadow: {0}", [count(n, [t("строка"), t("строки"), t("строк")])]),
  account: "Аккаунт",
  accountHint: "логин:пароль из карточки noshadow",
  otherAccount: "Другой…",
  countries: "Страны",
  country: "Страна",
  countrySearch: "Найти страну",
  anyCountry: "Любая",
  keep: "Не менять",
  mode: "IP",
  rotation: "Ротация",
  sticky: "Один IP",
  minutes: "Минут",
  transport: "Порт",
  http: "http 6969",
  socks: "socks 9696",
  perCountry: "На страну",
  total: (n: number) => t("Добавится: {0}", [count(n, [t("строка"), t("строки"), t("строк")])]),
  generate: "Добавить",
  apply: "Применить",
  cancel: "Отмена",
  bulk: "Настроить noshadow",
  /** новая сессия — новый IP; тот же id держит прежний */
  renew: "Новый IP",
} as const)

/** Подпись режима в строке таблицы: «US · один IP 15 мин». */
export function noshadowMode(country: string, minutes: number): string {
  const mode = minutes > 0 ? t("один IP {0} мин", [minutes]) : t("ротация")
  return country ? `${country} · ${mode}` : mode
}

export const PROXIES_TOAST = localize({
  saved: (n: number) => t("Сохранено: {0}.", [count(n, ADDR)]),
  rotating: (n: number) => t("Со сменой IP: {0}.", [n]),
  empty: "Список прокси пуст.",
  notChecked: "Не удалось проверить прокси",
  notRotated: "Не удалось сменить IP",
  /** провайдер ответил, но адрес остался прежним */
  sameIp: "IP не сменился",
  /** один тост на подряд идущие сохранения — не складывать стопкой */
  id: "proxies-saved",
  edited: "Строка сохранена.",
  notEdited: "Не удалось сохранить строку",
  deleted: (addr: string) => t("Удалено: {0}.", [addr]),
  deletedMany: (n: number) => t("Удалено: {0}.", [count(n, ADDR)]),
  copied: (n: number) => t("Скопировано: {0}.", [count(n, ADDR)]),
  enabledMany: (n: number) => t("Включено: {0}.", [count(n, ADDR)]),
  disabledMany: (n: number) => t("Отключено: {0}.", [count(n, ADDR)]),
  notDeleted: "Не удалось удалить строку",
  added: (n: number) => t("Добавлено: {0}.", [count(n, ADDR)]),
  notAdded: "Не удалось добавить строки",
  enabled: (addr: string) => t("Включено: {0}.", [addr]),
  disabled: (addr: string) => t("Отключено: {0}.", [addr]),
  notToggled: "Не удалось изменить строку",
  notLogin: "Не удалось изменить отметку «вход»",
  notPublish: "Не удалось изменить отметку «публикация»",
  changed: (n: number) => t("Изменено: {0}.", [count(n, ADDR)]),
  notChanged: "Не удалось изменить строки",
  /** правка свела бы две строки в одну — сервер оставил бы одну из них */
  wouldMerge: "После правки строки совпадут — у каждой должна быть своя сессия.",
  noAccount: "Нужны логин и пароль noshadow.",
  renewed: (addr: string) => t("Новая сессия: {0} — IP будет другим.", [addr]),
} as const)

/* Строка «хватит ли прокси на потоки»: сколько аккаунтов сядет на один IP. */
export function capacityText(c: Capacity): string {
  switch (c.kind) {
    case "off":
      return t("Прокси выключены — все аккаунты пойдут с вашего IP.")
    case "empty":
      return t("Список прокси пуст — все аккаунты пойдут с вашего IP.")
    case "none":
      return t("Живых прокси нет — публикация не пойдёт.")
    case "short":
      return (
        t("Потоков {0}, живых прокси {1} —", [fmtInt(c.threads), fmtInt(c.alive)]) +
        t(" по {0} на один IP.", [count(c.perProxy, ACCOUNT)])
      )
    case "ok":
      return t("Потоков {0}, живых прокси {1} — хватает.", [fmtInt(c.threads), fmtInt(c.alive)])
  }
}

/** Когда строку проверяли: «2 мин назад». Без «проверено» — колонка уже
    называется «Проверена», и слово в каждой ячейке было лишним (обрезало
    значение на узкой колонке). Отметки нет — «ещё не проверялся»; отметка
    есть, но не число — так и говорим, а не «NaN дн назад». */
export function checkedAgo(checkedAt: number | null | undefined, now = Date.now()): string {
  if (checkedAt == null) return PROXIES_LABEL.unchecked
  const at = serverNumber(checkedAt)
  if (at == null) return PROXIES_LABEL.unreadable
  if (at === 0) return PROXIES_LABEL.unchecked
  return fmtAgo(at, now)
}

/** Обратный отсчёт до смены IP: «смена через 30 с»; null — ждать нечего. */
export function rotateWait(sec: number): string | null {
  if (sec <= 0) return null
  if (sec < 60) return t("смена через {0} с", [sec])
  return t("смена через {0} мин", [Math.ceil(sec / 60)])
}

/** Итог смены IP: адреса до и после; без них — просто «IP сменён». */
export function rotatedText(before?: string | null, after?: string | null): string {
  return before && after ? t("IP сменён: {0} → {1}.", [before, after]) : t("IP сменён.")
}

/** Итог смены IP словами и тоном для тоста.

    Сервер отвечает `ok: true` и когда адрес остался прежним (`reason` = «IP не
    сменился»), поэтому по одному `ok` судить нельзя: сравниваем адреса до и
    после. Причины сервера строчные («провайдер просит подождать») — как и любой
    его текст, они идут через `sentence()`, иначе тост начинается со строчной. */
export function rotateOutcome(res: {
  ok?: boolean
  ip_before?: string | null
  ip_after?: string | null
  reason?: string | null
}): { ok: boolean; text: string } {
  const { ip_before: before, ip_after: after } = res
  // адрес назван и не изменился — провайдер не сменил IP, хотя ссылку дёрнули
  const same = !!before && before === after
  if (res.ok && !same) return { ok: true, text: rotatedText(before, after) }
  const why =
    sentence(res.reason || "") ||
    sentence(same ? PROXIES_TOAST.sameIp : PROXIES_TOAST.notRotated)
  // названный адрес дописываем после двоеточия — точка перед ним лишняя
  return { ok: false, text: same ? `${why.replace(/\.$/, "")}: ${before}.` : why }
}
