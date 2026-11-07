import { localize, t } from "@/lib/i18n"
/* Тексты экрана «Аккаунты»: короткие подписи, тосты — законченные
   предложения, подтверждения — вопрос и одно предложение о последствиях. */

export const ACCOUNTS_LABEL = localize({
  search: "Поиск по логину или стране",
  filters: "Срез списка",
  columns: "Колонки",
} as const)

export const FILTER_LABEL = localize({
  ready: "Готовы",
  all: "Все",
  nologin: "Без входа",
  shadow: "В тени",
  banned: "Отключены",
} as const)

/* Заголовки колонок: они же подписи к числам в строке на узком экране. */
export const COLUMN_LABEL = localize({
  name: "Аккаунт",
  region: "Страна",
  followers: "Подписчики",
  likes: "Лайки",
  views: "Просмотры",
  posts: "Посты",
  shadow: "В тени",
  fetched: "Обновлён",
} as const)

export const VERIFIED = "Галочка"
export const PRIVATE = "Закрытый профиль"
export const HAS_TOTP = "Код из 2FA"
export const HAS_EMAIL = "Код с почты"

/** Карточка аккаунта сбоку. */
export const CARD_LABEL = localize({
  session: "Вход сохранён",
  noSession: "Без входа",
  numbers: "Числа",
  visitors: "Посетители",
  privatePosts: "Скрытые",
  following: "Подписки",
  lastRun: "Последний прогон",
  posts: (done: string, of: string) => t("постов {0} из {1}", [done, of]),
  log: "Логи",
  logEmpty: "Записей о нём пока нет",
} as const)

/* Копирование юзернейма — с собакой, как он выглядит в TikTok. Кнопка одна и
   в строке, и в панели выделения: выделен один — она же говорит про один. */
export const COPY_LABEL = localize({
  one: "Скопировать",
  many: "Скопировать",
  toastOne: "Юзернейм скопирован.",
  toastMany: (n: number) => t("Скопировано юзернеймов: {0}.", [n]),
} as const)

/* Подписи пунктов строки и панели — кроме копирования: у него подпись зависит
   от числа аккаунтов и живёт в COPY_LABEL. */
export const ACCOUNT_ACTION = localize({
  publish: "Опубликовать",
  refresh: "Обновить",
  login: "Войти",
  open: "Открыть в TikTok",
  edit: "Изменить",
  purge: "Очистить посты",
  /* Локально: программа забывает сохранённый вход, у TikTok сессия жива. */
  clearSession: "Забыть",
  /* По-настоящему: гасит сессию и у TikTok (modules/login.remote_logout). */
  logout: "Выйти",
  disable: "Отключить",
  delete: "Удалить",
  more: "Действия",
} as const)

export const HEAD_ACTION = localize({
  add: "Добавить",
  loginAll: "Войти во все",
  refresh: "Обновить",
  refreshing: "Обновляем…",
} as const)

export const RUN_VERB = localize({
  login: "Вхожу",
  clearSession: "Забываю вход",
  logout: "Выхожу",
  purge: "Чищу",
  delete: "Удаляю",
} as const)

export const ADD_LABEL = localize({
  title: "Добавить аккаунты",
  placeholder:
    "логин:пароль — по строке на аккаунт. 2FA-секрет или почту можно добавить. Или вставьте JSON с куки TikTok",
  adding: "Добавляем…",
  close: "Закрыть",
} as const)

/* Правка одного аккаунта: логин, пароль сменился или определился неверно при
   вставке, источник 2FA. Форма подгружает настоящие секреты аккаунта
   (GET /api/accounts/secrets) и показывает их как есть, открытым текстом —
   типичная причина открыть форму это сверить, не разъехались ли логин с
   паролем при автоматическом разборе вставленного списка. */
export const EDIT_LABEL = localize({
  title: (u: string) => t("Изменить {0}", [u]),
  loading: "Загружаем сохранённые данные…",
  loadError: "Не удалось загрузить сохранённые данные",
  retry: "Повторить",
  username: "Логин",
  password: "Пароль",
  totp: "2FA-секрет",
  totpPlaceholder: "нет — вставьте, если появился",
  email: "Почта",
  emailPassword: "Пароль почты",
  emailPlaceholder: "нет",
  emailPasswordPlaceholder: "нет",
  save: "Сохранить",
  saving: "Сохраняем…",
  cancel: "Отмена",
  sourceHint:
    "2FA-секрет и почта необязательны. Для аккаунта, добавленного по куки, пароль можно не указывать.",
} as const)

export const EDIT_TOAST = localize({
  saved: (u: string) => t("Аккаунт {0} обновлён.", [u]),
  notSaved: "Не сохранилось",
} as const)

export const BANNED_LABEL = localize({
  restore: "Вернуть",
  at: "Отключён",
} as const)

export const SELECT_LABEL = localize({
  count: (n: number) => t("Выбрано: {0}", [n]),
  all: "Выбрать все",
  none: "Снять выделение",
  pick: (name: string) => t("Выбрать {0}", [name]),
  more: "Ещё",
  actions: "Действия",
  stop: "Остановить",
  stopping: "Останавливаю…",
} as const)

/* Пусто бывает по-разному, и каждый раз человеку нужен свой следующий шаг:
   в «Готовы» — войти, в «Без входа» и «В тени» это хорошая новость. */
export const EMPTY_LABEL = localize({
  none: "Аккаунтов пока нет",
  get add() { return ADD_LABEL.title },
  allBanned: "Все аккаунты отключены",
  allBannedText: "Рабочих аккаунтов сейчас нет — остались только отключённые.",
  notFound: "Ничего не найдено",
  clearSearch: "Очистить поиск",
  ready: "Готовых аккаунтов нет",
  readyText: "Вход не выполнен или все посты в тени.",
  showShadow: "Показать в тени",
  nologin: "Вход есть везде",
  nologinText: "Аккаунтов без сохранённого входа не осталось.",
  shadow: "Теней нет",
  shadowText: "Ни один пост не помечен как скрытый из поиска.",
  banned: "Отключённых нет",
  bannedText: "Отключённые аккаунты попадают сюда сами после публикации.",
} as const)

export const ACC_CONFIRM = localize({
  purgeOne: (u: string) => t("Очистить все посты на {0}?", [u]),
  purgeDesc:
    "Удалятся все публикации аккаунта. Вернуть их нельзя, ход виден в логах.",
  purgeMany: (n: number) =>
    t("Очистить все посты на выбранных аккаунтах ({0} шт.)?", [n]),
  purgeManyDesc:
    "Удалятся все публикации этих аккаунтов. Вернуть их нельзя, ход виден в логах.",
  purgeYes: "Очистить",
  clearSessionOne: (u: string) => t("Забыть вход в аккаунт {0}?", [u]),
  clearSessionMany: (n: number) =>
    t("Забыть вход в выбранные аккаунты ({0} шт.)?", [n]),
  clearSessionDesc:
    "Сохранённый вход удалится только из программы. У TikTok сессия останется рабочей — это не настоящий выход. Аккаунт останется в списке, и в него можно будет войти снова.",
  clearSessionYes: "Забыть",
  logoutOne: (u: string) => t("Выйти из аккаунта {0}?", [u]),
  logoutMany: (n: number) => t("Выйти из выбранных аккаунтов ({0} шт.)?", [n]),
  logoutDesc:
    "Настоящий выход: сессия перестанет действовать и у TikTok, даже в браузере. Нужен будет новый вход.",
  logoutYes: "Выйти",
  deleteOne: (u: string) => t("Удалить аккаунт {0}?", [u]),
  deleteDesc:
    "Сохранённый вход тоже удалится, войти заново с этого компьютера будет нельзя. У TikTok сессия при этом останется рабочей до истечения своих кук — программа её уже не увидит.",
  deleteLogoutFirst: "Перед удалением выйти у TikTok по-настоящему",
  newDevice: "Сменить устройство",
  deleteMany: (n: number) => t("Удалить выбранные аккаунты ({0} шт.)?", [n]),
  deleteYes: "Удалить",
  loginMany: (n: number) => t("Войти в выбранные аккаунты ({0} шт.)?", [n]),
  loginAll: (n: number) =>
    t("Войти во все аккаунты без сохранённого входа ({0} шт.)?", [n]),
  loginDesc: (n: number) =>
    t("Это займёт ~1 минуту на аккаунт, всего до ~{0} мин. Окно можно не закрывать.", [n]),
  loginYes: "Войти",
  loginAllYes: "Войти во все",
} as const)

export const ACC_TOAST = localize({
  purging: (u: string) => t("Очищаю посты на {0}, ход в логах.", [u]),
  restored: (u: string) => t("Аккаунт {0} возвращён в список.", [u]),
  disabled: (n: number) => t("Отключено: {0}.", [n]),
  undo: "Отменить",
  undone: (n: number) => t("Вернулось: {0}.", [n]),
  added: (n: number) => t("Добавлено аккаунтов: {0}.", [n]),
  /* Вставленный второй раз список не выглядит новым: у аккаунта с тем же
     логином заменяются поля, и об этом надо сказать — иначе человек узнает о
     подмене пароля или секрета 2FA только при следующем входе. */
  updated: (n: number) => t("Обновлено аккаунтов: {0}.", [n]),
  replaced: (words: string[]) => t("Заменены: {0}.", [words.join(", ")]),
  campLocked: "Нельзя менять аккаунты, пока идёт публикация.",
  campLogin: "Идёт публикация — вход недоступен.",
  notAdded: "Не добавлено",
  notRestored: "Не вернулось",
  notDisabled: "Не отключилось",
  notPurged: "Не вышло",
  notRefreshed: "Профили не обновлены",
} as const)

/* Поля ответа сервера — словами: механику («totp_secret») пользователю читать
   незачем. Незнакомое поле пропускаем: так в тост не просочится ключ. */
const REPLACED_WORD: Record<string, string> = localize({
  password: "пароль",
  totp_secret: "код 2FA",
  email: "почта",
  email_password: "пароль почты",
  session: "сессия",
})

export const replacedWords = (fields: string[]) => [
  ...new Set(fields.map((f) => REPLACED_WORD[f]).filter(Boolean)),
]

/* Прогон уже идёт, а просят другой — называем работу существительным:
   «идёт вход» читается, «идёт вхожу» — нет. */
const RUN_NOUN = localize({
  login: "вход",
  clearSession: "забывание входа",
  logout: "выход из аккаунта",
  purge: "очистка постов",
  delete: "удаление",
} as const)

export const RUN_TOAST = localize({
  otherRunning: (
    kind: "login" | "clearSession" | "logout" | "purge" | "delete"
  ) => t("Сейчас идёт {0}. Дождитесь или остановите.", [RUN_NOUN[kind]]),
  done: (
    kind: "login" | "clearSession" | "logout" | "purge" | "delete",
    stopped: boolean,
    ok: number,
    total: number
  ) => {
    const what =
      kind === "login"
        ? t("вошли")
        : kind === "clearSession"
          ? t("забыт вход у")
          : kind === "logout"
            ? t("вышли")
            : kind === "purge"
              ? t("очищено")
              : t("удалено")
    return t("{0}: {1} {2} из {3}.", [stopped ? "Остановлено" : "Готово", what, ok, total])
  },
  bannedLine: (list: string[]) =>
    t("Отключено: {0} ({1}).", [list.length, list.join(", ")]),
  failLine: (u: string, reason: string) => `${u} — ${reason}`,
} as const)
