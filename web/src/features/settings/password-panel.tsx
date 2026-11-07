import { useLanguage } from "@/lib/i18n"
import { useRef, useState } from "react"
import { LogOutIcon } from "lucide-react"

import { saveSettings, signOut } from "@/api/misc"
import type { Settings } from "@/api/types"
import { confirmDestructive } from "@/components/confirm"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { notify } from "@/lib/notify"

import { PASSWORD_LABEL, PASSWORD_TOAST } from "./labels"
import { SettingsGroup } from "./settings-row"

/* Пароль сервера: задаётся и снимается явно, автосохранения нет — случайный
   набор не должен запереть программу. */
export function PasswordPanel({
  password,
}: {
  password: Settings["password"]
}) {
  useLanguage()
  const [value, setValue] = useState("")
  const [saving, setSaving] = useState(false)
  const guard = useRef(false)

  const apply = async () => {
    if (value.length < password.min_len || guard.current) return
    guard.current = true
    setSaving(true)
    try {
      await saveSettings({ password: value })
      setValue("")
      notify.ok(PASSWORD_TOAST.set)
    } catch (error) {
      notify.error(error)
    } finally {
      guard.current = false
      setSaving(false)
    }
  }

  const remove = async () => {
    if (guard.current) return
    guard.current = true
    if (
      !(await confirmDestructive({
        title: PASSWORD_TOAST.confirmRemove,
        confirmText: PASSWORD_LABEL.remove,
      }))
    ) {
      guard.current = false
      return
    }
    setSaving(true)
    try {
      await saveSettings({ password: "" })
      notify.ok(PASSWORD_TOAST.removed)
    } catch (error) {
      notify.error(error)
    } finally {
      guard.current = false
      setSaving(false)
    }
  }

  const exit = async () => {
    try {
      await signOut()
    } finally {
      location.reload()
    }
  }

  return (
    <SettingsGroup title={PASSWORD_LABEL.title}>
      <FieldGroup className="p-4">
        <FieldDescription>
          {PASSWORD_LABEL.hint}{" "}
          {!password.required ? PASSWORD_LABEL.localHint : null}
        </FieldDescription>
        <Field>
          <FieldLabel htmlFor="settings-password">
            {PASSWORD_LABEL.field}
          </FieldLabel>
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
            <Input
              className="min-w-0 flex-1"
              id="settings-password"
              type="password"
              autoComplete="new-password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  void apply()
                }
              }}
            />
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button
                disabled={saving || value.length < password.min_len}
                onClick={() => void apply()}
              >
                {PASSWORD_LABEL.set}
              </Button>
              {password.set ? (
                <Button
                  variant="outline"
                  disabled={saving}
                  onClick={() => void remove()}
                >
                  {PASSWORD_LABEL.remove}
                </Button>
              ) : null}
            </div>
          </div>
        </Field>
        {password.set && password.required ? (
          <Button
            variant="ghost"
            className="self-start"
            disabled={saving}
            onClick={() => void exit()}
          >
            <LogOutIcon data-icon="inline-start" />
            {PASSWORD_LABEL.exit}
          </Button>
        ) : null}
      </FieldGroup>
    </SettingsGroup>
  )
}
