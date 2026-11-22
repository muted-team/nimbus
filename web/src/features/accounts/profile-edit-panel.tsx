import { useEffect, useRef, useState } from "react"
import type { Account } from "@/api/types"
import {
  readTikTokProfile,
  updateTikTokProfile,
  type ProfileChanges,
  type ProfileInfo,
  type ProfileResult,
  type ProfileStep,
} from "@/api/profile-edit"
import { ApiError } from "@/api/client"
import { Button } from "@/components/ui/button"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Spinner } from "@/components/ui/spinner"
import { t, useLanguage } from "@/lib/i18n"
import {
  profileNeedsReadback,
  profileOutcome,
  usernameStepText,
} from "./profile-edit-result"
import { accountUsername, atUsername } from "./username"

const RESULT_LABEL: Record<string, string> = {
  confirmed: "Изменения подтверждены повторным чтением",
  partial: "Подтверждена только часть изменений",
  noop: "Поля уже совпадают; изменения не отправлены",
  blocked: "Изменение остановлено",
  rejected: "TikTok отклонил изменение",
  unknown: "Результат не подтверждён. Перечитайте профиль перед повтором",
}

export function ProfileEditPanel({
  account,
  onClose,
}: {
  account: Account
  onClose: () => void
}) {
  useLanguage()
  const [info, setInfo] = useState<ProfileInfo | null>(null)
  const [nickname, setNickname] = useState("")
  const [uniqueId, setUniqueId] = useState("")
  const [avatar, setAvatar] = useState("")
  const [acknowledge, setAcknowledge] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [result, setResult] = useState<ProfileResult | null>(null)
  const [outcome, setOutcome] = useState("")
  const [readbackRequired, setReadbackRequired] = useState(false)
  const inFlight = useRef(false)
  const readGeneration = useRef(0)
  const fileGeneration = useRef(0)
  const [imageLoading, setImageLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const setObserved = (observed: ProfileInfo) => {
    setInfo(observed)
    setNickname(observed.before.nickname)
    setUniqueId(observed.before.unique_id)
    fileGeneration.current += 1
    setImageLoading(false)
    setAvatar("")
    setAcknowledge(false)
    setReadbackRequired(false)
    if (fileRef.current) fileRef.current.value = ""
  }
  useEffect(() => {
    let active = true
    const generation = ++readGeneration.current
    void readTikTokProfile(account.username)
      .then((observed) => {
        if (!active || readGeneration.current !== generation) return
        setObserved(observed)
        if (observed.last_result) {
          setResult(observed.last_result)
          setOutcome(
            profileOutcome(
              observed.last_result,
              observed.last_requested ?? {},
              observed.last_expected_uid ?? observed.before.user_id
            )
          )
        }
      })
      .catch((failure: unknown) => {
        if (active)
          setError(
            failure instanceof ApiError
              ? failure.message
              : t("Не удалось прочитать профиль")
          )
      })
    return () => {
      active = false
    }
  }, [account.username])
  const read = async () => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setError("")
    const generation = ++readGeneration.current
    try {
      const observed = await readTikTokProfile(account.username)
      if (readGeneration.current === generation) setObserved(observed)
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : t("Не удалось прочитать профиль")
      )
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const file = async (selected: File | undefined) => {
    const generation = ++fileGeneration.current
    setImageLoading(false)
    setAvatar("")
    setError("")
    if (!selected) return
    if (
      selected.size > 2 * 1024 * 1024 ||
      !["image/png", "image/jpeg", "image/webp"].includes(selected.type)
    ) {
      setError(t("Выберите PNG, JPEG или WebP до 2 МБ"))
      if (fileRef.current) fileRef.current.value = ""
      return
    }
    setImageLoading(true)
    const reader = new FileReader()
    reader.onload = () => {
      if (fileGeneration.current !== generation) return
      setImageLoading(false)
      if (typeof reader.result === "string") setAvatar(reader.result)
    }
    reader.onerror = () => {
      if (fileGeneration.current !== generation) return
      setImageLoading(false)
      setError(t("Не удалось прочитать изображение"))
    }
    reader.readAsDataURL(selected)
  }
  const policyMessage = (field: "nickname" | "unique_id") => {
    const policy = info?.policies?.[field]
    if (policy?.changeable !== false) return ""
    return typeof policy.next_change_at === "number" &&
      Number.isFinite(policy.next_change_at)
      ? t("Следующая смена доступна после {0}", [
          new Date(policy.next_change_at * 1000).toLocaleString(),
        ])
      : t("Повторная смена временно ограничена TikTok")
  }
  const changes: ProfileChanges = {}
  if (info && nickname !== info.before.nickname) changes.nickname = nickname
  if (info && uniqueId !== info.before.unique_id) changes.unique_id = uniqueId
  if (avatar) changes.avatar_data = avatar
  const requiresAck =
    changes.nickname !== undefined || changes.unique_id !== undefined
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (
      !info ||
      imageLoading ||
      inFlight.current ||
      readbackRequired ||
      !Object.keys(changes).length
    )
      return
    inFlight.current = true
    setBusy(true)
    setError("")
    setResult(null)
    setOutcome("")
    const requested = { ...changes }
    try {
      const response = await updateTikTokProfile(
        account.username,
        requested,
        info.before.user_id,
        acknowledge
      )
      setResult(response)
      const verifiedOutcome = profileOutcome(
        response,
        requested,
        info.before.user_id
      )
      setOutcome(verifiedOutcome)
      if (
        ["confirmed", "partial"].includes(verifiedOutcome) &&
        response.after?.user_id === info.before.user_id
      ) {
        setInfo({ ...info, before: response.after })
        if (verifiedOutcome === "confirmed") {
          setNickname(response.after.nickname)
          setUniqueId(response.after.unique_id)
          setAcknowledge(false)
        }
        if (response.confirmed_fields?.includes("avatar_data")) {
          setAvatar("")
          if (fileRef.current) fileRef.current.value = ""
        }
      }
      setReadbackRequired(profileNeedsReadback(response, verifiedOutcome))
    } catch (failure) {
      const message =
        failure instanceof ApiError
          ? failure.message
          : t("Результат не подтверждён. Перечитайте профиль перед повтором")
      setError(message)
      if (
        !(failure instanceof ApiError) ||
        ![400, 404, 422].includes(failure.status)
      )
        setReadbackRequired(true)
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const steps: ProfileStep[] = Array.isArray(result?.steps)
    ? result.steps.filter(
        (step) =>
          !!step &&
          typeof step.step === "string" &&
          typeof step.verdict === "string"
      )
    : []
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent className="gap-0">
        <SheetHeader>
          <SheetTitle>
            {t("Профиль TikTok")} · {atUsername(info?.before.unique_id || accountUsername(account) || account.username)}
          </SheetTitle>
          <SheetDescription>
            {t(
              "Имя, username и аватар меняются в TikTok. Сохранённый вход остаётся в этой записи"
            )}
          </SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          {result ? (
            <Alert>
              <AlertDescription>
                {outcome ? (
                  <p>{t(RESULT_LABEL[outcome] ?? RESULT_LABEL.unknown)}</p>
                ) : null}
                {result.message &&
                !(result.verdict === "confirmed" && outcome === "unknown") ? (
                  <p>{t(result.message)}</p>
                ) : null}
                {result.error ? <p>{t(result.error)}</p> : null}
                {Array.isArray(result.confirmed_fields) &&
                result.confirmed_fields.length ? (
                  <p>
                    {t("Подтверждённые поля")}:{" "}
                    {result.confirmed_fields
                      .map((field) =>
                        t(
                          (
                            {
                              nickname: "Отображаемое имя",
                              unique_id: "Имя пользователя (username)",
                              avatar_data: "Аватар",
                            } as Record<string, string>
                          )[field] ?? "Неизвестное поле"
                        )
                      )
                      .join(", ")}
                  </p>
                ) : null}
                {result.state_saved === false ? (
                  <p>
                    {t(
                      result.state_error ||
                        "Состояние не сохранено. Перечитайте профиль перед повтором"
                    )}
                  </p>
                ) : null}
                {steps.map((step, index) => (
                  <p key={index}>
                    {step.step === "username_update"
                      ? t(
                          outcome === "unknown" && step.verdict === "confirmed"
                            ? "Сервер сообщил подтверждение шага; требуется проверка профиля"
                            : usernameStepText(step)
                        )
                      : `${t(({ avatar_upload: "Загрузка аватара", profile_update: "Имя и аватар" } as Record<string, string>)[step.step] ?? "Шаг изменения профиля")}: ${t(({ confirmed: "подтверждено", rejected: "отклонено", blocked: "остановлено", unknown: "результат неизвестен", uploaded: "загружено" } as Record<string, string>)[step.verdict] ?? "неизвестный статус")}`}
                    {typeof step.code === "number" &&
                    Number.isInteger(step.code)
                      ? ` · ${t("Код TikTok")}: ${step.code}`
                      : ""}
                  </p>
                ))}
                {result.after?.unique_id ? (
                  <p>
                    {t("Имя при повторном чтении")}: @{result.after.unique_id}
                  </p>
                ) : null}
              </AlertDescription>
            </Alert>
          ) : null}
          {!info ? (
            <p role="status">{t("Чтение профиля")}</p>
          ) : (
            <form onSubmit={submit} className="flex flex-col gap-4">
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="profile-nickname">
                    {t("Отображаемое имя")}
                  </FieldLabel>
                  <Input
                    id="profile-nickname"
                    value={nickname}
                    onChange={(event) => setNickname(event.target.value)}
                    disabled={
                      busy || info.policies?.nickname?.changeable === false
                    }
                  />
                  {policyMessage("nickname") ? (
                    <FieldDescription>
                      {policyMessage("nickname")}
                    </FieldDescription>
                  ) : null}
                  <FieldDescription>
                    {t(
                      "Можно использовать Unicode и эмодзи. Повторная смена обычно через 7 дней"
                    )}
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="profile-username">
                    {t("Имя пользователя (username)")}
                  </FieldLabel>
                  <Input
                    id="profile-username"
                    value={uniqueId}
                    onChange={(event) => setUniqueId(event.target.value)}
                    disabled={
                      busy || info.policies?.unique_id?.changeable === false
                    }
                    autoCapitalize="none"
                    spellCheck={false}
                  />
                  {policyMessage("unique_id") ? (
                    <FieldDescription>
                      {policyMessage("unique_id")}
                    </FieldDescription>
                  ) : null}
                  <FieldDescription>
                    {t(
                      "Буквы, цифры, точки и подчёркивания; без точки в конце. Текущий сервер принимает 2–24 символа. Смена меняет ссылку на профиль и обычно доступна раз в 30 дней"
                    )}
                  </FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor="profile-avatar">
                    {t("Новый аватар")}
                  </FieldLabel>
                  <Input
                    ref={fileRef}
                    id="profile-avatar"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    onChange={(event) => void file(event.target.files?.[0])}
                    disabled={
                      busy ||
                      info.policies?.avatar_data?.native_supported === false
                    }
                  />
                  <FieldDescription>
                    {t("PNG, JPEG или WebP до 2 МБ")}
                  </FieldDescription>
                </Field>
                {requiresAck ? (
                  <Field orientation="horizontal">
                    <Checkbox
                      id="profile-cooldown"
                      checked={acknowledge}
                      onCheckedChange={(checked) =>
                        setAcknowledge(checked === true)
                      }
                      disabled={busy}
                    />
                    <FieldLabel htmlFor="profile-cooldown">
                      {t("Понимаю сроки повторной смены имени и username")}
                    </FieldLabel>
                  </Field>
                ) : null}
              </FieldGroup>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="submit"
                  disabled={
                    busy ||
                    imageLoading ||
                    readbackRequired ||
                    !Object.keys(changes).length ||
                    (requiresAck && !acknowledge)
                  }
                >
                  {busy ? <Spinner /> : null}
                  {t("Применить в TikTok")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void read()}
                >
                  {t("Перечитать профиль")}
                </Button>
              </div>
            </form>
          )}
          {!info ? (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => void read()}
            >
              {t("Перечитать профиль")}
            </Button>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
