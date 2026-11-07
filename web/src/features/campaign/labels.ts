import { localize, t } from "@/lib/i18n"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CirclePauseIcon,
  Loader2Icon,
  TimerIcon,
  type LucideIcon,
} from "lucide-react"

import type { CampaignState, CampaignStep, Creatives, MediaKind, RepeatUnit } from "@/api/types"
import { userMessage } from "@/api/client"
import type { Tone } from "@/components/status"
import { atUsername } from "@/features/accounts/username"
import { count, fmtInt } from "@/lib/format"

/* Все подписи публикации — в одном месте: экран публикации, карточка аккаунта, строки
   аккаунтов и подтверждения берут их отсюда. */

export const STATE_LABEL: Record<CampaignState, { text: string; tone: Tone; icon: LucideIcon; spin?: boolean }> = localize({
  idle: { text: "Не запускалась", tone: "neutral", icon: CirclePauseIcon },
  running: { text: "Идёт", tone: "live", icon: Loader2Icon, spin: true },
  stopping: { text: "Останавливается", tone: "warn", icon: Loader2Icon, spin: true },
  waiting: { text: "Ждёт круг", tone: "warn", icon: TimerIcon },
  stopped: { text: "Завершена", tone: "ok", icon: CircleCheckIcon },
  error: { text: "Ошибка", tone: "bad", icon: CircleAlertIcon },
})

export const STEP_LABEL: Record<CampaignStep, string> = localize({
  rotate: "смена IP",
  cleanup: "очистка постов",
  login: "вход",
  wait_proxy: "ждёт прокси",
  notices: "уведомления",
  publishing: "публикация",
})

export const stepLabel = (step: string) => STEP_LABEL[step as CampaignStep] ?? step

export const MEDIA_LABEL: Record<MediaKind, string> = localize({
  photo: "Фото",
  video: "Видео",
})

/** Режимы креативов; у видео «копии разные» и «одна копия» — одно и то же. */
export const CREATIVES_LABEL: Record<MediaKind, Partial<Record<Creatives, string>>> = localize({
  photo: {
    unique: "Разные фото",
    copies: "Одно фото, копии разные",
    single: "Одно фото, одна копия",
  },
  video: {
    unique: "Разные видео",
    single: "Одно видео",
  },
})

export const REPEAT_UNIT_LABEL: Record<RepeatUnit, { plural: string; short: string }> = localize({
  min: { plural: "минут", short: "мин" },
  hour: { plural: "часов", short: "ч" },
})

/** Пункты выбора единицы повтора. */
export const REPEAT_UNIT_ITEMS = (Object.keys(REPEAT_UNIT_LABEL) as RepeatUnit[]).map((value) => ({
  value,
  get label() { return REPEAT_UNIT_LABEL[value].plural },
}))

/** Снято за нарушение правил — сама беда, без указания, чего считаем. Числа с
    этой подписью стоят на одном экране дважды, и рядом всегда сказано, что за
    число: аккаунты в строке «Отчёт» (OUTCOME_LABEL.removed) и в блоке
    скопированного отчёта (REPORT_BLOCK.removed), посты в панели результатов
    (RESULTS_LABEL.removed). Без слова одно читалось бы за другое. */
export const REMOVED_TEXT = "Снято за нарушение правил"

/** Итог аккаунта в строке «Отчёт»: пролит, не пролит, забанен, со снятыми
    постами. Число здесь — аккаунты, и у снятых постов оно подписано словом. */
export const OUTCOME_LABEL = localize({
  published: { tone: "ok", label: (n: number) => t("Опубликовано {0}", [fmtInt(n)]) },
  failed: { tone: "warn", label: (n: number) => t("Не опубликовано {0}", [fmtInt(n)]) },
  banned: { tone: "bad", label: (n: number) => t("Забанено {0}", [fmtInt(n)]) },
  removed: {
    tone: "bad",
    label: (n: number) => t("{0}: {1}", [t(REMOVED_TEXT), count(n, [t("аккаунт"), t("аккаунта"), t("аккаунтов")])]),
  },
} as const) satisfies Record<string, { label: (n: number) => string; tone: Tone }>

export type ReportOutcome = keyof typeof OUTCOME_LABEL

/** Строка результатов: опубликованные делятся на целиком и частично. */
export const RESULT_LABEL = localize({
  full: { text: "Опубликовано", tone: "ok" },
  partial: { text: "Частично", tone: "warn" },
  failed: { text: "Не опубликовано", tone: "warn" },
  banned: { text: "Забанено", tone: "bad" },
} as const) satisfies Record<string, { text: string; tone: Tone }>

export type ResultOutcome = keyof typeof RESULT_LABEL

/* ── форма ──────────────────────────────────────────────────────────── */

export const FORM_LABEL = localize({
  content: "Контент",
  title: "Заголовок",
  caption: "Описание",
  folders: { photo: "Папки", video: "Папка с видео" } satisfies Record<MediaKind, string>,
  addFolder: "Добавить папку",
  browse: "Обзор",
  upload: "Загрузить",
  removeFolder: "Убрать папку",
  folderPath: "Путь к папке",
  params: "Параметры",
  posts: "Постов на аккаунт",
  delay: "Пауза, с",
  /** режим повтора файлов между постами (разные / одна копия и т.п.); не
      «Креативы» — так уже называется сам раздел, в котором стоит это поле */
  creatives: "Режим",
  processing: "Обработка",
  /** что происходит с файлами, когда пост ушёл */
  keep: { photo: "Опубликованные фото", video: "Опубликованные видео" } satisfies Record<MediaKind, string>,
  cleanup: "Очистка перед публикацией",
  cleanupCount: "Сколько постов",
  repeat: "Повторять кругами",
  repeatEvery: "Через",
  repeatUnit: "Единица",
} as const)

export const TITLE_MAX = 90
export const CAPTION_MAX = 4000

export const KEEP_LABEL = localize({ delete: "Удалять", keep: "Оставлять" } as const)

export type CleanupMode = "same" | "all" | "count"

export const CLEANUP_MODE_LABEL: Record<CleanupMode, string> = localize({
  same: "По числу новых",
  all: "Все",
  count: "Число",
})

/** Что принимает «Загрузить» в браузере. */
export const UPLOAD_ACCEPT: Record<MediaKind, string> = {
  photo: "image/*,.heic,.heif,.avif",
  video: "video/*,.mp4,.mov,.m4v,.webm,.mkv,.avi",
}

/** Выбор папки в форме: папки программы (из «Креативов») или своя. */
export const FOLDER_LABEL = localize({
  library: "Папки программы",
  own: "Своя папка",
  /** счётчик в списке папок программы: то, что пойдёт в публикацию */
  count: (photos: number, videos: number, media: MediaKind) =>
    media === "video" ? t("видео {0}", [fmtInt(videos)]) : t("фото {0}", [fmtInt(photos)]),
  /** та же кнопка «Из галереи», что и в «Креативах», но эта сразу добавляет
      папку в публикацию — подпись должна отличаться, а не повторять кнопку
      в шапке раздела, которая только заводит папку в библиотеку */
  fromGallery: "Загрузить и добавить",
} as const)

/** Счётчик у строки папки: сколько в ней фото (видео) для публикации. */
export const SLOT_LABEL = localize({
  photos: (n: number) => t("фото {0}", [fmtInt(n)]),
  videos: (n: number) => t("видео {0}", [fmtInt(n)]),
  missing: "нет папки",
  uploading: (done: number, total: number) => t("загрузка {0}/{1}", [done, total]),
} as const)

/** Нехватка файлов в папке: сколько нужно и сколько есть. */
const needFiles = (media: MediaKind, need: number, have: number) =>
  t("нужно {0} {1}, есть {2}", [fmtInt(need), MEDIA_LABEL[media].toLowerCase(), fmtInt(have)])

/** Строка папки и подтверждение запуска говорят об одном и том же, поэтому
    число нужно-и-есть считается одним местом. */
export const SHORTAGE_LABEL = localize({
  /** значение в подтверждении запуска */
  need: needFiles,
  /** строка у папки, которой не хватит на проход */
  row: (media: MediaKind, need: number, have: number) => t("Не хватит: {0}", [needFiles(media, need, have)]),
  /** имя папки-слота в подтверждении: у видео она одна и без номера */
  folder: (media: MediaKind, index: number) => (media === "video" ? t("Папка") : t("Папка {0}", [fmtInt(index + 1)])),
} as const)

export const ERROR_TEXT = localize({
  int1: "Целое число от 1",
  num0: "Число от 0",
  order: "«От» больше «до»",
  folder: "Папка для публикации не выбрана",
} as const)

/** Поля, у которых бывает ошибка, — в порядке проверки перед запуском. */
export const FIELD_ORDER = ["folders", "posts", "delay", "cleanupCount", "repeat"] as const
export type FieldKey = (typeof FIELD_ORDER)[number]

/** Подпись поля в тосте об ошибке, когда запуск пришёл не с экрана публикации. */
export function fieldLabel(field: FieldKey, media: MediaKind): string {
  switch (field) {
    case "folders":
      return FORM_LABEL.folders[media]
    case "posts":
      return FORM_LABEL.posts
    case "delay":
      return t("Пауза")
    case "cleanupCount":
      return t("Очистка")
    case "repeat":
      return t("Повтор")
  }
}

/* ── ход и результаты ───────────────────────────────────────────────── */

export const PROGRESS_LABEL = localize({
  posts: "Постов",
  accounts: "Аккаунты",
  failed: "Не опубликовано",
  round: "Круг",
  nextRound: "Следующий круг",
  started: "Начало",
  finished: "Конец",
  reason: "Итог",
  workers: "В работе",
  report: "Отчёт",
  idle: "Публикация не запускалась",
} as const)

export const RESULTS_LABEL = localize({
  title: "Результаты",
  account: "Аккаунт",
  copy: "Скопировать отчёт",
  empty: "Результатов пока нет",
  /** слово отдельно от числа: на узком экране кнопка показывает только число
      (в шапке карточки не помещаются оба слова), слово остаётся в aria-label */
  retryWord: "Повторить неудачные",
  retry: (n: number) => t("Повторить неудачные ({0})", [n]),
  /** сколько постов снял TikTok — в строке результата и в плашке панели; это
      посты, а не аккаунты: число аккаунтов подписано в OUTCOME_LABEL.removed */
  removed: (n: number) => t("{0}: {1}", [t(REMOVED_TEXT), count(n, [t("пост"), t("поста"), t("постов")])]),
} as const)

/** Отчёт поднят с диска после перезапуска (campaign.py, поле restored) — это
    итог прошлого запуска, а не ход текущего. Строка одна и на карточке
    «Результаты», и в скопированном отчёте: иначе одно и то же называлось бы
    по-разному. */
export const RESTORED_TEXT = "Отчёт прошлого запуска"

/** Заголовки блоков отчёта, который копируется в буфер. */
export const REPORT_BLOCK: Record<ReportOutcome, string> = localize({
  published: "Пролитые",
  failed: "Не пролитые",
  banned: "Забаненные",
  removed: REMOVED_TEXT,
})

/** Исходы, у которых в тексте отчёта рядом с именем стоит причина: с ними
    дальше работают — войти заново, сменить прокси, подождать капчу. У
    пролитых и со снятыми постами причина не нужна, там только имена. */
export const REPORT_WITH_REASON: readonly ReportOutcome[] = ["failed", "banned"]

/** Строка блока отчёта: юзернейм с собакой (как в «Аккаунтах») и причина,
    если она есть. Причина отделена тире, а не двоеточием: в самих причинах
    двоеточие уже стоит («сессия не проверена: …») и читалось бы как второе
    имя поля. */
export const reportLine = (account: string, reason?: string | null) =>
  reason ? `${atUsername(account)} — ${userMessage(reason)}` : atUsername(account)

/* ── запуск ─────────────────────────────────────────────────────────── */

export const LAUNCH_LABEL = localize({
  start: "Запустить",
  starting: "Запускаем…",
  stop: "Остановить",
  stopping: "Останавливаем…",
  open: "Открыть",
  progress: "Прогон",
} as const)

export const CONFIRM_LABEL = localize({
  all: "Запустить публикацию?",
  descAll: "Один проход по всем аккаунтам. Это реальные публикации, не тест.",
  descSelected: "Один проход по выбранным аккаунтам. Это реальные публикации, не тест.",
  accounts: "Аккаунты",
  posts: "Постов на аккаунт",
  content: "Контент",
  mode: "Режим",
  after: "После публикации",
  cleanup: "Очистка",
  repeat: "Повтор",
  kept: "останутся",
  deleted: "удалятся",
  allPosts: "все посты",
  stop: "Остановить публикацию?",
  stopDesc: "Аккаунты в работе доведут текущий пост и остановятся.",
} as const)

export const TOAST = localize({
  started: "Публикация запущена.",
  notStarted: "Не запущено",
  stopping: "Останавливаем — после текущего поста.",
  notStopped: "Не остановлено",
  running: "Публикация уже идёт.",
  copied: "Отчёт скопирован.",
  notSaved: "Форма публикации не сохранена",
  notLoaded: "Форма публикации не загружена",
  noFolder: "Укажите папку.",
  notPicked: "Папка не выбрана",
} as const)

/* ── экран публикации: обработка, сводка, первый запуск ─────────────── */

export const PROCESSING_LABEL = localize({
  setup: "Настроить",
  video: "Видео уходит как есть: уникализация — только для фото.",
  active: (n: number, total: number) => t("{0} из {1}", [fmtInt(n), fmtInt(total)]),
  notSaved: "Уникализация не сохранена",
} as const)

export const SUMMARY_LABEL = localize({
  title: "Сводка",
  posts: "Постов",
  postsValue: (accounts: number, per: number) => `${fmtInt(accounts)} × ${fmtInt(per)} = ${fmtInt(accounts * per)}`,
  noLogin: (n: number) => t("без входа {0}", [fmtInt(n)]),
  shadow: (n: number) => t("в тени {0}", [fmtInt(n)]),
  deadProxies: "живых прокси нет",
  attention: "Внимание",
  /** форма правится во время прогона — это уже для следующего запуска */
  nextRun: "Правки — для следующего запуска",
  running: "Идёт прогон",
} as const)

/** Чек-лист первого запуска: пустое состояние учит одному действию за раз. */
export const CHECKLIST_LABEL = localize({
  title: "Первый запуск",
  accounts: "Добавить аккаунты",
  proxies: "Добавить прокси",
  media: "Загрузить креативы",
  launch: "Запустить публикацию",
  open: "Открыть",
} as const)

export const RUN_LABEL = localize({
  posts: "Посты",
  left: "Осталось",
  accounts: "Аккаунты",
  failed: "Не опубликовано",
  workers: "В работе",
  log: "Логи прогона",
  logEmpty: "Записей пока нет",
  more: (n: number) => t("и ещё {0}", [fmtInt(n)]),
} as const)
