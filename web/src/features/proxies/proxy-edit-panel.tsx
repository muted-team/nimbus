import { useLanguage } from "@/lib/i18n"
import { useState } from "react"

import { SimpleSelect } from "@/components/simple-select"
import { Button } from "@/components/ui/button"
import { Field } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { sentence } from "@/lib/format"
import { notify } from "@/lib/notify"

import { PROXIES_TOAST, PROXY_EDIT_LABEL } from "./labels"
import { buildProxyLine, parseProxyLine, type ProxyLineFields } from "./proxy-line"
import { saveProxiesLines } from "./proxies-store"

/* Правка одной строки — по отдельным полям, не одной текстовой строкой:
   протокол выбором из списка, хост, порт, логин, пароль (как есть, посимвольно
   — так же сделано в правке аккаунта) и отдельно необязательная ссылка смены
   IP. Строка в `data.proxies[index]` уже лежит в каноническом виде (её
   собирает разбор сервера при добавлении) — расклад по полям и сборка обратно
   читают ровно этот вид (см. proxy-line.ts), другие форматы сюда не попадают.

   Строку, которая на канонический вид не похожа (ручная правка руками мимо
   формы, старый формат), не теряем молча — правим её одним полем как есть. */

const SCHEME_ITEMS = [
  { value: "http", label: "http" },
  { value: "socks5", label: "socks5" },
  { value: "socks4", label: "socks4" },
] as const

const EMPTY_FIELDS: ProxyLineFields = {
  scheme: "http",
  login: "",
  password: "",
  host: "",
  port: "",
  rotateUrl: "",
}

export function ProxyEditPanel({
  index,
  addr,
  proxies,
  login,
  publish,
  off,
  onClose,
}: {
  /** номер строки в исходном списке — тот же, что у смены IP */
  index: number
  /** адрес без учётки — для заголовка панели */
  addr: string
  /** полный список строк (с учётками) на момент открытия панели */
  proxies: string[]
  /** правка строки не должна снимать её отметки */
  login: number[]
  publish: number[]
  off: number[]
  onClose: () => void
}) {
  useLanguage()
  const line = proxies[index] ?? ""
  const parsed = parseProxyLine(line)
  const [broken] = useState(!parsed)
  const [raw, setRaw] = useState(line)
  const [fields, setFields] = useState<ProxyLineFields>(parsed ?? EMPTY_FIELDS)
  const [saving, setSaving] = useState(false)

  const set = (key: keyof ProxyLineFields) => (v: string) => setFields((f) => ({ ...f, [key]: v }))

  const value = broken ? raw : buildProxyLine(fields)
  const empty = !value.trim()
  const missingParts = !broken && (!fields.host.trim() || !fields.port.trim())

  const save = async () => {
    if (empty || missingParts) return
    setSaving(true)
    try {
      const next = [...proxies]
      next[index] = value.trim()
      const res = await saveProxiesLines(next, { login, publish, off })
      const error = res?.errors?.[0]?.error
      if (error) {
        notify.warn(sentence(error))
        return
      }
      notify.ok(PROXIES_TOAST.edited)
      onClose()
    } catch (error) {
      notify.error(error, PROXIES_TOAST.notEdited)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="gap-0">
        <SheetHeader>
          <SheetTitle>{PROXY_EDIT_LABEL.title(addr)}</SheetTitle>
          {broken ? <SheetDescription>{PROXY_EDIT_LABEL.brokenHint}</SheetDescription> : null}
        </SheetHeader>
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
          {broken ? (
            <Field>
              <Label htmlFor="proxy-edit-raw">{PROXY_EDIT_LABEL.line}</Label>
              <Input
                id="proxy-edit-raw"
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
                aria-invalid={empty || undefined}
              />
            </Field>
          ) : (
            <>
              <Field>
                <Label htmlFor="proxy-edit-scheme">{PROXY_EDIT_LABEL.scheme}</Label>
                <SimpleSelect
                  value={fields.scheme}
                  items={SCHEME_ITEMS}
                  onValueChange={set("scheme")}
                  aria-label={PROXY_EDIT_LABEL.scheme}
                />
              </Field>
              <div className="flex gap-3">
                <Field className="min-w-0 flex-1">
                  <Label htmlFor="proxy-edit-host">{PROXY_EDIT_LABEL.host}</Label>
                  <Input
                    id="proxy-edit-host"
                    value={fields.host}
                    onChange={(e) => set("host")(e.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono"
                    aria-invalid={!fields.host.trim() || undefined}
                  />
                </Field>
                <Field className="w-24 shrink-0">
                  <Label htmlFor="proxy-edit-port">{PROXY_EDIT_LABEL.port}</Label>
                  <Input
                    id="proxy-edit-port"
                    value={fields.port}
                    onChange={(e) => set("port")(e.target.value)}
                    inputMode="numeric"
                    autoComplete="off"
                    spellCheck={false}
                    className="font-mono"
                    aria-invalid={!fields.port.trim() || undefined}
                  />
                </Field>
              </div>
              <Field>
                <Label htmlFor="proxy-edit-login">{PROXY_EDIT_LABEL.login}</Label>
                <Input
                  id="proxy-edit-login"
                  value={fields.login}
                  onChange={(e) => set("login")(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono"
                />
              </Field>
              <Field>
                <Label htmlFor="proxy-edit-password">{PROXY_EDIT_LABEL.password}</Label>
                <Input
                  id="proxy-edit-password"
                  value={fields.password}
                  onChange={(e) => set("password")(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono"
                />
              </Field>
              <Field>
                <Label htmlFor="proxy-edit-rotate">{PROXY_EDIT_LABEL.rotateUrl}</Label>
                <Input
                  id="proxy-edit-rotate"
                  value={fields.rotateUrl}
                  onChange={(e) => set("rotateUrl")(e.target.value)}
                  placeholder={PROXY_EDIT_LABEL.rotateUrlPlaceholder}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono"
                />
              </Field>
            </>
          )}
        </div>
        <SheetFooter className="flex-row justify-end gap-2 border-t">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {PROXY_EDIT_LABEL.cancel}
          </Button>
          <Button onClick={() => void save()} disabled={saving || empty || missingParts}>
            {saving ? PROXY_EDIT_LABEL.saving : PROXY_EDIT_LABEL.save}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
