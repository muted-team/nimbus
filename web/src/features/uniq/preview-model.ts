import { localize } from "@/lib/i18n"
import { FolderOpenIcon, ImageOffIcon, VideoOffIcon, type LucideIcon } from "lucide-react"

import type { MediaKind } from "@/api/types"

/* Что превью показывает вместо картинки. Уникализатор меняет только фото,
   поэтому в режиме видео превью по фото-папкам не рисуем: смена режима эти
   папки нарочно не теряет, и к текущему проходу они отношения не имеют. */

export type PreviewEmpty = "loading" | "video" | "noFolders" | "off"

/**
 * Пустое состояние превью — оно же и запрет на сборку: null значит «превью
 * можно собирать». Режим видео важнее прочего: вопрос пользователя в нём не
 * про папки, а про то, применяется ли уникализатор к роликам.
 */
export function previewEmpty(
  media: MediaKind,
  folders: string[],
  foldersReady: boolean,
  master: boolean,
): PreviewEmpty | null {
  if (!foldersReady) return "loading"
  if (media === "video") return "video"
  if (folders.length === 0) return "noFolders"
  if (!master) return "off"
  return null
}

/** Заголовок и пояснение пустого превью — теми же словами, что в инструкции. */
export const PREVIEW_EMPTY: Record<
  Exclude<PreviewEmpty, "loading">,
  { icon: LucideIcon; title: string; text?: string }
> = localize({
  video: {
    icon: VideoOffIcon,
    title: "К видео не применяется",
    text: "Ролик уходит в TikTok как есть. Параметры слева — для фото.",
  },
  noFolders: { icon: FolderOpenIcon, title: "Папки не выбраны" },
  off: { icon: ImageOffIcon, title: "Уникализация выключена" },
})
