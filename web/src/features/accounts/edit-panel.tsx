import { useLanguage } from "@/lib/i18n"
import { useState } from "react"

import { updateAccount, useAccountSecrets } from "@/api/accounts"
import { ApiError } from "@/api/client"
import type { Account, AccountPatch, AccountSecrets } from "@/api/types"
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
import { Skeleton } from "@/components/ui/skeleton"
import { notify } from "@/lib/notify"

import { EDIT_LABEL, EDIT_TOAST } from "./labels"

/* Ручная правка одного аккаунта: пароль сменился, логин определился неверно
   при массовой вставке, поменялась почта или 2FA. Форма при открытии
   загружает настоящие секреты аккаунта (GET /api/accounts/secrets, useQuery
   без кэша между открытиями — см. useAccountSecrets) и заполняет ими поля
   как есть, открытым текстом: типичная причина зайти сюда это свериться
   посимвольно, не опечатался ли при вводе или вставке. Список аккаунтов
   (GET /api/accounts) секретов не несёт нарочно, поэтому пока они грузятся,
   форма показывает свой отдельный загрузочный запрос.

   Правка считается по сравнению с загруженным значением: поле изменили —
   идёт в patch, оставили как было — не идёт (сервер не трогает поле,
   которого нет в patch); очистили — идёт пустой строкой (сервер снимает
   поле, кроме username/password — они обязательны всегда). */

interface Draft {
  username: string
  password: string
  totp: string
  email: string
  emailPassword: string
}

function draftFrom(username: string, secrets: AccountSecrets): Draft {
  return {
    username,
    password: secrets.password ?? "",
    totp: secrets.totp_secret ?? "",
    email: secrets.email ?? "",
    emailPassword: secrets.email_password ?? "",
  }
}

export function EditPanel({ account, onClose }: { account: Account; onClose: () => void }) {
  useLanguage()
  const secretsQuery = useAccountSecrets(account.username)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [draftFor, setDraftFor] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // черновик заводим из ответа ровно один раз за открытие панели: дальше это
  // поле человека, повторный тот же ответ запроса (рефетч в фоне) его не сотрёт
  const secrets = secretsQuery.data
  if (secrets && draftFor !== account.username) {
    setDraft(draftFrom(account.username, secrets))
    setDraftFor(account.username)
  }

  const set = (key: keyof Draft) => (value: string) => {
    setDraft((d) => (d ? { ...d, [key]: value } : d))
  }

  if (!draft || !secrets) {
    return (
      <Sheet open onOpenChange={(open) => !open && onClose()}>
        <SheetContent className="gap-0">
          <SheetHeader>
            <SheetTitle>{EDIT_LABEL.title(account.username)}</SheetTitle>
          </SheetHeader>
          <div className="flex flex-1 flex-col gap-4 px-4 pb-4">
            {secretsQuery.isError ? (
              <div className="flex flex-col items-start gap-2 pt-2 text-sm text-muted-foreground">
                {EDIT_LABEL.loadError}
                <Button variant="outline" size="sm" onClick={() => void secretsQuery.refetch()}>
                  {EDIT_LABEL.retry}
                </Button>
              </div>
            ) : (
              <>
                <span className="text-sm text-muted-foreground">{EDIT_LABEL.loading}</span>
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>
    )
  }

  const usernameChanged = draft.username.trim() !== account.username
  const usernameEmpty = !draft.username.trim()
  const passwordEmpty = !draft.password.trim() && (!!secrets.password || !account.has_session)

  const save = async () => {
    const patch: AccountPatch = {}
    if (usernameChanged) patch.username = draft.username.trim()
    if (draft.password !== (secrets.password ?? "")) patch.password = draft.password
    if (draft.totp !== (secrets.totp_secret ?? "")) patch.totp_secret = draft.totp.trim()
    if (draft.email !== (secrets.email ?? "")) patch.email = draft.email.trim()
    if (draft.emailPassword !== (secrets.email_password ?? ""))
      patch.email_password = draft.emailPassword.trim()

    if (!Object.keys(patch).length) {
      onClose()
      return
    }
    setSaving(true)
    try {
      await updateAccount(account.username, patch)
      notify.ok(EDIT_TOAST.saved(patch.username ?? account.username))
      onClose()
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) notify.warn(error.message)
      else notify.error(error, EDIT_TOAST.notSaved)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="gap-0">
        <SheetHeader>
          <SheetTitle>{EDIT_LABEL.title(account.username)}</SheetTitle>
          <SheetDescription>{EDIT_LABEL.sourceHint}</SheetDescription>
        </SheetHeader>
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
          <Field>
            <Label htmlFor="edit-username">{EDIT_LABEL.username}</Label>
            <Input
              id="edit-username"
              value={draft.username}
              onChange={(e) => set("username")(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={usernameEmpty || undefined}
            />
          </Field>
          <Field>
            <Label htmlFor="edit-password">{EDIT_LABEL.password}</Label>
            <Input
              id="edit-password"
              value={draft.password}
              onChange={(e) => set("password")(e.target.value)}
              autoComplete="new-password"
              spellCheck={false}
              aria-invalid={passwordEmpty || undefined}
              className="font-mono"
            />
          </Field>
          <Field>
            <Label htmlFor="edit-totp">{EDIT_LABEL.totp}</Label>
            <Input
              id="edit-totp"
              value={draft.totp}
              onChange={(e) => set("totp")(e.target.value)}
              placeholder={EDIT_LABEL.totpPlaceholder}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          </Field>
          <Field>
            <Label htmlFor="edit-email">{EDIT_LABEL.email}</Label>
            <Input
              id="edit-email"
              value={draft.email}
              onChange={(e) => set("email")(e.target.value)}
              placeholder={EDIT_LABEL.emailPlaceholder}
              autoComplete="off"
              spellCheck={false}
            />
          </Field>
          <Field>
            <Label htmlFor="edit-email-password">{EDIT_LABEL.emailPassword}</Label>
            <Input
              id="edit-email-password"
              value={draft.emailPassword}
              onChange={(e) => set("emailPassword")(e.target.value)}
              placeholder={EDIT_LABEL.emailPasswordPlaceholder}
              autoComplete="new-password"
              spellCheck={false}
              className="font-mono"
            />
          </Field>
        </div>
        <SheetFooter className="flex-row justify-end gap-2 border-t">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {EDIT_LABEL.cancel}
          </Button>
          <Button
            onClick={() => void save()}
            disabled={saving || usernameEmpty || passwordEmpty}
          >
            {saving ? EDIT_LABEL.saving : EDIT_LABEL.save}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
