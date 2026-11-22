import { useLanguage } from "@/lib/i18n"
import { useRef, useState } from "react"
import { Dice5Icon, EyeIcon, EyeOffIcon, LogOutIcon } from "lucide-react"

import { saveSettings, signOut } from "@/api/misc"
import type { Settings } from "@/api/types"
import { confirmDestructive } from "@/components/confirm"
import { Hint } from "@/components/hint"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { notify } from "@/lib/notify"

import { PASSWORD_LABEL, PASSWORD_TOAST } from "./labels"
import { ACCESS_TEXT } from "./access-labels"
import { generatePassword } from "./password-generator"

/* Пароль сервера: задаётся и снимается явно, автосохранения нет — случайный
   набор не должен запереть программу. */
export function PasswordPanel({
  password,
  networkActive = false,
}: {
  password: Settings["password"]
  networkActive?: boolean
}) {
  const text = ACCESS_TEXT[useLanguage()]
  const [value, setValue] = useState("")
  const [revealed, setRevealed] = useState(false)
  const [saving, setSaving] = useState(false)
  const guard = useRef(false)

  const apply = async () => {
    if (value.length < password.min_len || guard.current) return
    guard.current = true
    setSaving(true)
    try {
      await saveSettings({ password: value })
      setValue("")
      setRevealed(false)
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
    <FieldGroup className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={password.set ? "secondary" : "outline"}>
          {password.set ? PASSWORD_TOAST.set : text.notSet}
        </Badge>
      </div>
      <FieldDescription>
        {PASSWORD_LABEL.hint}{" "}
        {!password.required ? PASSWORD_LABEL.localHint : null}
      </FieldDescription>
      <Field>
        <FieldLabel htmlFor="settings-password">
          {PASSWORD_LABEL.field}
        </FieldLabel>
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
          <InputGroup className="min-w-0 flex-1">
            <InputGroupInput
              id="settings-password"
              type={revealed ? "text" : "password"}
              autoComplete="new-password"
              value={value}
              disabled={saving}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  void apply()
                }
              }}
            />
            <InputGroupAddon align="inline-end">
              <Hint label={revealed ? text.hide : text.show}>
                <InputGroupButton
                  size="icon-sm"
                  aria-label={revealed ? text.hide : text.show}
                  aria-pressed={revealed}
                  disabled={saving || !value}
                  onClick={() => setRevealed(!revealed)}
                >
                  {revealed ? <EyeOffIcon /> : <EyeIcon />}
                </InputGroupButton>
              </Hint>
              <Hint label={text.generate}>
                <InputGroupButton
                  size="icon-sm"
                  aria-label={text.generate}
                  disabled={saving}
                  onClick={() => {
                    setValue(generatePassword(password.min_len))
                    setRevealed(false)
                  }}
                >
                  <Dice5Icon />
                </InputGroupButton>
              </Hint>
            </InputGroupAddon>
          </InputGroup>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              disabled={saving || value.length < password.min_len}
              onClick={() => void apply()}
            >
              {PASSWORD_LABEL.set}
            </Button>
            {password.set ? (
              <Hint label={PASSWORD_LABEL.remove} reason={text.removeHint}>
                <Button
                  variant="outline"
                  disabled={saving || networkActive}
                  onClick={() => void remove()}
                >
                  {PASSWORD_LABEL.remove}
                </Button>
              </Hint>
            ) : null}
          </div>
        </div>
        <FieldDescription>{text.draftHint}</FieldDescription>
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
  )
}
