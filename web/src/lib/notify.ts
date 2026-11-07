import { t } from "@/lib/i18n"
import { toast, type ExternalToast } from "sonner"

import { errorText, userMessage } from "@/api/client"

/* Тосты — разовые события. Текст — законченное предложение с точкой; длинные
   списки режем до трёх строк, остальное — «и ещё N». Ошибки держатся дольше. */

const MAX_LINES = 3

function describe(lines?: string[]): string | undefined {
  if (!lines?.length) return undefined
  const shown = lines.slice(0, MAX_LINES).map(userMessage)
  if (lines.length > MAX_LINES) shown.push(t("И ещё {0}.", [lines.length - MAX_LINES]))
  return shown.join("\n")
}

type Options = Omit<ExternalToast, "description"> & { lines?: string[] }

function withLines({ lines, ...rest }: Options = {}): ExternalToast {
  return { ...rest, description: describe(lines) }
}

export const notify = {
  ok: (text: string, opts?: Options) => toast.success(text, withLines(opts)),
  info: (text: string, opts?: Options) => toast.info(userMessage(text), withLines(opts)),
  warn: (text: string, opts?: Options) => toast.warning(userMessage(text), { duration: 6000, ...withLines(opts) }),
  error: (error: unknown, prefix?: string, opts?: Options) =>
    toast.error(errorText(error, prefix), {
      duration: 8000,
      ...withLines(opts),
    }),
}
