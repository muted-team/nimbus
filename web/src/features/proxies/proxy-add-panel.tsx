import { useLanguage } from "@/lib/i18n"
import { useRef, useState } from "react"
import { GlobeIcon, XIcon } from "lucide-react"

import { Panel } from "@/components/panel"
import { RejectedLines } from "@/components/rejected-lines"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup } from "@/components/ui/field"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { remainingLineDraft } from "@/lib/line-draft"
import { notify } from "@/lib/notify"

import { NOSHADOW_LABEL, PROXIES_TOAST, PROXY_ADD_LABEL } from "./labels"
import { saveProxiesLines } from "./proxies-store"

/* Добавление пачкой: вставленные строки дописываются к тому, что уже на
   сервере, и уходят одним PUT (другого способа дописать список нет —
   PUT заменяет его целиком). Непринятые строки остаются в поле с причиной
   под ним, как в добавлении аккаунтов. */

export function ProxyAddPanel({
  proxies,
  login,
  publish,
  off,
  onClose,
  onNoshadow,
}: {
  /** текущий полный список строк (с учётками) — новые дописываются к нему */
  proxies: string[]
  /** отметки существующих строк сохраняются вместе с новым списком */
  login: number[]
  publish: number[]
  off: number[]
  onClose: () => void
  /** открыть сборку строк noshadow — вместо ручной вставки */
  onNoshadow: () => void
}) {
  useLanguage()
  const [text, setText] = useState("")
  const [errors, setErrors] = useState<{ line: number; error: string }[]>([])
  const [adding, setAdding] = useState(false)
  const current = useRef("")
  const inFlight = useRef(false)

  const submit = async () => {
    const sent = current.current
    if (inFlight.current || !sent.trim()) return
    inFlight.current = true
    setAdding(true)
    try {
      const offset = proxies.length
      // Не убираем пустые строки до запроса: номера ошибок относятся к вводу.
      const res = await saveProxiesLines([...proxies, sent], { login, publish, off })
      if (!res) return
      const errs = (res.errors ?? [])
        .filter((e) => e.line > offset)
        .map((e) => ({ ...e, line: e.line - offset }))
      const rest = remainingLineDraft(sent, current.current, errs)
      current.current = rest.text
      setText(rest.text)
      setErrors(rest.errors)
      const added = Math.max(0, res.proxies.length - offset)
      if (added) notify.ok(PROXIES_TOAST.added(added))
      if (!rest.text.trim()) onClose()
    } catch (error) {
      notify.error(error, PROXIES_TOAST.notAdded)
    } finally {
      inFlight.current = false
      setAdding(false)
    }
  }

  return (
    <Panel
      title={PROXY_ADD_LABEL.title}
      actions={
        <Button variant="ghost" size="icon-xs" aria-label={PROXY_ADD_LABEL.close} disabled={adding} onClick={() => !inFlight.current && onClose()}>
          <XIcon />
        </Button>
      }
    >
      <FieldGroup className="gap-3">
        <Field data-invalid={errors.length > 0 || undefined}>
          <Textarea
            value={text}
            onChange={(e) => {
              current.current = e.target.value
              setText(e.target.value)
              setErrors([])
            }}
            rows={4}
            placeholder={PROXY_ADD_LABEL.placeholder}
            spellCheck={false}
            autoComplete="off"
            aria-label={PROXY_ADD_LABEL.title}
            aria-busy={adding || undefined}
            aria-invalid={errors.length > 0 || undefined}
            className="min-h-24 resize-y font-mono text-sm"
          />
        </Field>
        {errors.length ? (
          <RejectedLines errors={errors} />
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" size="sm" disabled={adding} onClick={() => !inFlight.current && onNoshadow()}>
            <GlobeIcon data-icon="inline-start" />
            {NOSHADOW_LABEL.open}
          </Button>
          <Button onClick={() => void submit()} disabled={adding || !text.trim()}>
            {adding ? <Spinner data-icon="inline-start" /> : null}
            {adding ? PROXY_ADD_LABEL.adding : PROXY_ADD_LABEL.add}
          </Button>
        </div>
      </FieldGroup>
    </Panel>
  )
}
