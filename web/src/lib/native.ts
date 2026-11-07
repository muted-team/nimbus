import { t } from "@/lib/i18n"
/* Мост к окну программы (pywebview). В браузере по ссылке его нет: системного
   «Обзора» папки там не будет — вместо него загрузка файлов на сервер. */

import { notify } from "@/lib/notify"

interface PywebviewApi {
  pick_folder: () => Promise<string | null>
}

declare global {
  interface Window {
    pywebview?: { api?: PywebviewApi }
  }
}

export const hasNativeWindow = () => Boolean(window.pywebview?.api)

export async function pickFolder(): Promise<string | null> {
  const bridge = window.pywebview?.api
  return bridge ? bridge.pick_folder() : null
}

/** pywebview внедряет api иногда уже после первой отрисовки. */
export function onNativeReady(callback: () => void) {
  window.addEventListener("pywebviewready", callback)
  return () => window.removeEventListener("pywebviewready", callback)
}

/** Текст в буфер: современный API, иначе execCommand (http без TLS, окно программы). */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    return navigator.clipboard.writeText(text)
  }
  const ta = document.createElement("textarea")
  ta.value = text
  ta.style.position = "fixed"
  ta.style.opacity = "0"
  document.body.appendChild(ta)
  ta.select()
  const ok = document.execCommand("copy")
  ta.remove()
  if (!ok) throw new Error(t("буфер обмена недоступен"))
}

/** Копирует и подтверждает тостом: буфера человек не видит, а молчание после
    нажатия читается как сбой. Не вышло — тост с ошибкой, не исключение. Пустой
    текст не копируем (тихо, false). Истина — скопировано. */
export async function copyWithToast(
  text: string,
  okMessage = t("Скопировано."),
  failMessage = t("Не удалось скопировать")
): Promise<boolean> {
  if (!text) return false
  try {
    await copyText(text)
    notify.ok(okMessage)
    return true
  } catch (error) {
    notify.error(error, failMessage)
    return false
  }
}

/** Открыть ссылку: в окне программы уходит в системный браузер. */
export function openExternal(url: string) {
  window.open(url, "_blank", "noopener")
}

export const tiktokProfileUrl = (username: string) =>
  `https://www.tiktok.com/@${encodeURIComponent(username)}`
