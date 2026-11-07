import { useLanguage } from "@/lib/i18n"
import { useEffect, useRef, useState } from "react"
import { XIcon } from "lucide-react"

import { addAccountsBulk, refreshAccounts } from "@/api/accounts"
import { ApiError } from "@/api/client"
import type { BulkAddResponse } from "@/api/types"
import { Panel } from "@/components/panel"
import { RejectedLines } from "@/components/rejected-lines"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { notify } from "@/lib/notify"

import { remainingDraft, submissionText } from "./add-draft"
import { addedToast } from "./add-result"
import { ADD_LABEL, ACC_TOAST } from "./labels"

/* Массовое добавление: вставил список — отправилось само, без кнопки.
   Разобранные строки уходят в список, неразобранные остаются в поле с причиной
   под ним. Тот же текст повторно не отправляем.

   При наборе руками уходят только законченные строки — те, после которых уже
   нажали Enter. Иначе пауза посреди набора отправляла кусок строки: сервер
   принимал обрезанный 2FA-секрет (ему хватает 16 символов) и перезаписывал им
   существующий аккаунт. Вставку и закрытие панели отправляем целиком: там
   последняя строка законченная, даже если перевода строки в конце нет. */

const SUBMIT_DELAY = 800

export function AddPanel({ onClose }: { onClose: () => void }) {
  useLanguage()
  const [text, setText] = useState("")
  const [errors, setErrors] = useState<BulkAddResponse["errors"]>([])
  const [adding, setAdding] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const lastSent = useRef<string | null>(null)
  const current = useRef("")
  const inFlight = useRef(false)
  const pending = useRef<{ whole: boolean } | null>(null)
  /** правка пришла вставкой — отправляем и последнюю строку без перевода */
  const pasted = useRef(false)

  useEffect(() => () => {
    window.clearTimeout(timer.current)
    pending.current = null
  }, [])

  const takePending = () => {
    const next = pending.current
    pending.current = null
    return next
  }

  /** whole — отправить и незаконченную последнюю строку (вставка, закрытие). */
  const submit = async (value: string, whole: boolean) => {
    window.clearTimeout(timer.current)
    if (inFlight.current) {
      pending.current = { whole: whole || !!pending.current?.whole }
      return
    }
    pending.current = null
    const head = submissionText(value, whole)
    if (!head?.trim() || head === lastSent.current) return
    lastSent.current = head
    inFlight.current = true
    setAdding(true)
    try {
      const res = await addAccountsBulk(head)
      const toast = addedToast(res)
      if (toast) {
        notify.ok(toast.text, { lines: toast.lines })
        void refreshAccounts()
      }
      const rest = remainingDraft(head, current.current, res.errors)
      current.current = rest.text
      lastSent.current = rest.retained
      setText(rest.text)
      setErrors(rest.errors)
      if (!rest.text.trim()) onClose()
    } catch (error) {
      lastSent.current = null
      if (error instanceof ApiError && error.status === 409) notify.warn(ACC_TOAST.campLocked)
      else notify.error(error, ACC_TOAST.notAdded)
    } finally {
      inFlight.current = false
      setAdding(false)
      const queued = takePending()
      if (queued) void submit(current.current, queued.whole)
    }
  }

  const onChange = (value: string, whole = false) => {
    current.current = value
    setText(value)
    setErrors([])
    window.clearTimeout(timer.current)
    if (pending.current) pending.current.whole = whole
    timer.current = window.setTimeout(() => void submit(current.current, whole), SUBMIT_DELAY)
  }

  const close = () => {
    window.clearTimeout(timer.current)
    // Сначала ждём ответ: непринятый список или сбой должны остаться в поле.
    if (current.current.trim()) {
      if (current.current === lastSent.current && !inFlight.current) onClose()
      else void submit(current.current, true)
    } else if (!inFlight.current) onClose()
  }

  return (
    <Panel
      title={ADD_LABEL.title}
      meta={adding ? <Spinner aria-label={ADD_LABEL.adding} /> : null}
      actions={
        <Button variant="ghost" size="icon-xs" aria-label={ADD_LABEL.close} onClick={close}>
          <XIcon />
        </Button>
      }
    >
      <Textarea
        value={text}
        onPaste={() => {
          pasted.current = true
        }}
        onChange={(e) => {
          const whole = pasted.current
          pasted.current = false
          onChange(e.target.value, whole)
        }}
        rows={3}
        placeholder={ADD_LABEL.placeholder}
        spellCheck={false}
        autoComplete="off"
        aria-label={ADD_LABEL.title}
        aria-busy={adding || undefined}
        className="min-h-20 resize-y font-mono text-sm"
      />
      {errors.length ? (
        <RejectedLines errors={errors.map((e) => ({ line: e.line, error: e.reason }))} />
      ) : null}
    </Panel>
  )
}
