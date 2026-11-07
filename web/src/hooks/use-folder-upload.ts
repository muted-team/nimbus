import { localize, t } from "@/lib/i18n"
import { useEffect, useState } from "react"

import { errorText } from "@/api/client"
import { refreshMedia, uploadToFolder } from "@/api/misc"
import { notify } from "@/lib/notify"

/* Загрузка файлов в папку на компьютере с программой — из «Креативов» и из
   формы публикации. По файлу на запрос, по очереди: пришедший файл сразу на
   диске, и уход со страницы теряет только не отправленные. Пока идёт
   загрузка, уход переспрашивается. */

export interface FolderUpload {
  /** куда грузим — чтобы строка папки показала ход у себя */
  target: string
  done: number
  total: number
}

const TEXT = localize({
  uploaded: (done: number, total: number) => t("Загружено: {0} из {1}.", [done, total]),
} as const)

export function useFolderUpload() {
  const [state, setState] = useState<FolderUpload | null>(null)

  useEffect(() => {
    if (!state) return
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ""
    }
    window.addEventListener("beforeunload", guard)
    return () => window.removeEventListener("beforeunload", guard)
  }, [state])

  /** Файлы — в папку `folder` (путь на компьютере с программой). */
  async function upload(folder: string, files: File[]) {
    setState({ target: folder, done: 0, total: files.length })
    const failed: string[] = []
    for (const file of files) {
      try {
        await uploadToFolder(folder, file)
      } catch (error) {
        failed.push(`${file.name} — ${errorText(error)}`)
      }
      setState((s) => (s ? { ...s, done: s.done + 1 } : s))
    }
    setState(null)
    refreshMedia()
    const done = files.length - failed.length
    if (failed.length) notify.error(TEXT.uploaded(done, files.length), undefined, { lines: failed })
    else notify.ok(TEXT.uploaded(done, files.length))
  }

  return { state, upload }
}
