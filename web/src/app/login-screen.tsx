import { t, useLanguage } from "@/lib/i18n"
import { LogInIcon } from "lucide-react"
import { useState } from "react"

import { errorText } from "@/api/client"
import { signIn } from "@/api/misc"
import { Button } from "@/components/ui/button"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"

import { BrandMark, PRODUCT } from "./brand"

/* Вход по паролю: программа стоит на сервере, интерфейс открыт по ссылке.
   Окно программы на компьютере пароль не спрашивает. После входа страница
   перезагружается — проще и надёжнее, чем переигрывать все запросы. */
export function LoginScreen() {
  useLanguage()
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setError("")
    try {
      await signIn(password)
      location.reload()
    } catch (err) {
      setError(errorText(err))
      setPassword("")
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-4">
      <form onSubmit={submit} className="flex w-full max-w-xs flex-col gap-6">
        <div className="flex flex-col items-center gap-3">
          <BrandMark className="size-11 rounded-xl" />
          <h1 className="text-lg font-semibold">{PRODUCT}</h1>
        </div>
        <Field data-invalid={error ? true : undefined}>
          <FieldLabel htmlFor="password">{t("Пароль")}</FieldLabel>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "password-error" : undefined}
            className="h-10"
          />
          {error ? <FieldError id="password-error">{error}</FieldError> : null}
        </Field>
        <Button type="submit" size="lg" className="h-10" disabled={!password || busy}>
          {busy ? <Spinner /> : <LogInIcon />}{t("Войти")}</Button>
      </form>
    </main>
  )
}
