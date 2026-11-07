import { t } from "@/lib/i18n"
/* Обёртка над fetch: таймаут, JSON, понятная ошибка. Пути относительные —
   интерфейс может жить не в корне домена. 401 с {auth: true} значит, что
   сервер на замке (программа на сервере, интерфейс открыт по ссылке): об этом
   узнаёт стор входа, и приложение показывает экран пароля. */

export const DEFAULT_TIMEOUT = 20_000
/* Вход и массовое добавление: вход с кодом на почту ждёт письмо, и минуты ему
   мало. Лучше дольше подождать ответ, чем записать в неудачи вход, который
   сервер доводит до конца. */
export const LONG_TIMEOUT = 150_000

export class ApiError extends Error {
  readonly status: number
  readonly body: Record<string, unknown>

  constructor(message: string, status: number, body: Record<string, unknown> = {}) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

type AuthListener = () => void
const authListeners = new Set<AuthListener>()

/** Подписка на «сервер требует пароль». Возвращает отписку. */
export function onAuthRequired(listener: AuthListener) {
  authListeners.add(listener)
  return () => {
    authListeners.delete(listener)
  }
}

interface RequestOptions {
  timeout?: number
  /** сырое тело (файл) вместо JSON */
  raw?: BodyInit
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  { timeout = DEFAULT_TIMEOUT, raw }: RequestOptions = {}
): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  const init: RequestInit = { method, signal: ctrl.signal }
  if (raw !== undefined) {
    init.body = raw
  } else if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" }
    init.body = JSON.stringify(body)
  }

  try {
    const res = await fetch(path, init)
    let json: Record<string, unknown> = {}
    try {
      const parsed: unknown = await res.json()
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("expected JSON object")
      json = parsed as Record<string, unknown>
    } catch (error) {
      if (ctrl.signal.aborted) throw error
      // Ошибка HTTP бывает HTML-страницей прокси. Но успешный ответ без
      // нашего JSON нельзя превращать в подтверждение выполненной команды.
      if (res.ok) throw new ApiError(t("сервер вернул некорректный ответ"), res.status)
    }
    if (!res.ok) {
      if (res.status === 401 && json.auth) authListeners.forEach((fn) => fn())
      const message = typeof json.error === "string" ? json.error : `HTTP ${res.status}`
      throw new ApiError(message, res.status, json)
    }
    return json as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(
      ctrl.signal.aborted
        ? t("превышено время ожидания ({0} с)", [Math.round(timeout / 1000)])
        : t("сервер не отвечает"),
      0
    )
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("POST", path, body ?? {}, opts),
  put: <T>(path: string, body: unknown, opts?: RequestOptions) =>
    request<T>("PUT", path, body, opts),
  upload: <T>(path: string, file: Blob, opts?: RequestOptions) =>
    request<T>("POST", path, undefined, { timeout: 30 * 60_000, ...opts, raw: file }),
}

/** Причина без советов и административных действий, в том числе из старых логов.
 * Подробные диагностические записи остаются исходными. */
export function userMessage(text: string): string {
  return text.replace(/\s*(?:[—–;,]\s*|\.\s+)(?:обновите|проверьте|попробуйте|повторите|перезапустите|обратитесь|смените|сделайте)\s[\s\S]*$/i, "").trim()
}

/** Текст ошибки для тоста: с заглавной буквы и точкой в конце. */
export function errorText(error: unknown, prefix?: string): string {
  const raw = error instanceof Error ? error.message : String(error ?? "")
  const msg = userMessage(raw) || t("неизвестная ошибка")
  const sentence = prefix ? `${prefix}: ${msg}` : msg.charAt(0).toUpperCase() + msg.slice(1)
  return /[.!?…]$/.test(sentence) ? sentence : `${sentence}.`
}
