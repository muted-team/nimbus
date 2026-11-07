import { localize, t } from "@/lib/i18n"
import { fmtInt } from "@/lib/format"

/* Тексты раздела «Креативы» — папок программы (media/ рядом с ней). Форма
   публикации берёт отсюда же то, что говорит о тех же папках. */

const pad2 = (n: number) => String(n).padStart(2, "0")
/** «25.09 14-32» — метка времени в имени папки: двоеточие в имя папки нельзя. */
const stamp = (d: Date) =>
  `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)} ${pad2(d.getHours())}-${pad2(d.getMinutes())}`

export const LIB_LABEL = localize({
  folders: "Папки",
  newFolder: "Новая папка",
  upload: "Загрузить",
  path: "Путь к папке",
  dropInto: (name: string) => t("Отпустите — файлы лягут в «{0}»", [name]),
  dropNew: "Отпустите — файлы лягут в новую папку",
  name: "Имя",
  create: "Создать",
  more: "Ещё",
  clear: "Очистить",
  remove: "Удалить папку",
  removeFile: "Удалить файл",
  empty: "Папок пока нет",
  folderEmpty: "В папке пока пусто",
  /** «фото 64 · видео 3»; пустая — «пусто» */
  counts: (photos: number, videos: number) =>
    [photos ? t("фото {0}", [fmtInt(photos)]) : "", videos ? t("видео {0}", [fmtInt(videos)]) : ""].filter(Boolean).join(" · ") ||
    t("пусто"),
  /** имя папки, заведённой под загрузку без открытой папки */
  gallery: (d: Date) => t("Галерея {0}", [stamp(d)]),
  /** имя новой папки, если своё не ввели */
  dated: (d: Date) => t("Папка {0}", [stamp(d)]),
  clearAsk: (name: string) => t("Очистить папку «{0}»?", [name]),
  clearDesc: "Все фото и видео в ней удалятся с диска.",
  clearYes: "Очистить",
  removeAsk: (name: string) => t("Удалить папку «{0}»?", [name]),
  removeDesc: "Папка удалится с диска вместе с файлами.",
  removeYes: "Удалить",
} as const)

export const LIB_TOAST = localize({
  notCreated: "Папка не создана",
  cleared: (n: number) => t("Удалено файлов: {0}.", [fmtInt(n)]),
  notCleared: "Папка не очищена",
  removed: "Папка удалена.",
  notRemoved: "Папка не удалена",
  notFileRemoved: "Файл не удалён",
} as const)
