import { useEffect, useRef, useState } from "react"
import { refreshAccounts } from "@/api/accounts"
import {
  registrationCapabilities,
  registrationStatus,
  registrationHistory,
  cancelRegistration,
  type RegistrationCapabilities,
  type RegistrationStatus,
} from "@/api/registration"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NumberInput, parseNumber } from "@/components/number-input"
import { useProxies } from "@/api/proxies"
import { useLocation } from "wouter"
import { startRun, useAccountsRun } from "./accounts-run"
import { SimpleSelect } from "@/components/simple-select"
import { Spinner } from "@/components/ui/spinner"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { t, useLanguage } from "@/lib/i18n"
import {
  modeAvailable,
  registrationBusy,
  registrationPolling,
} from "./registration-view"

const STATUS: Record<RegistrationStatus["status"], string> = {
  idle: "Регистрация не запущена",
  queued: "В очереди",
  running: "Регистрация выполняется",
  complete: "Регистрация завершена",
  failed: "Регистрация не завершена",
  cancelled: "Регистрация отменена",
  dispatch_unknown: "Результат отправки неизвестен. Не повторяйте регистрацию",
  interrupted_or_unknown:
    "Результат требует проверки. Не создавайте аккаунт повторно",
}
export function RegistrationPanel({ onClose }: { onClose: () => void }) {
  useLanguage()
  const [caps, setCaps] = useState<RegistrationCapabilities | null>(null)
  const [job, setJob] = useState<RegistrationStatus>({ status: "idle" })
  const [loaded, setLoaded] = useState(false)
  const [capChecked, setCapChecked] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState("")
  const [mode, setMode] = useState<3 | 4>(4)
  const [token, setToken] = useState("")
  const [quantity, setQuantity] = useState("1")
  const run = useAccountsRun((store) => store.run)
  const current = useAccountsRun((store) => store.registrationCurrent)
  const results = useAccountsRun((store) => store.registrationResults)
  const pollError = useAccountsRun((store) => store.registrationPollError)
  const requestStop = useAccountsRun((store) => store.requestStop)
  const pool = useProxies().data
  const [, navigate] = useLocation()
  const count = parseNumber(quantity)
  const validCount =
    count !== null && Number.isInteger(count) && count >= 1 && count <= 50

  const [minimum, setMinimum] = useState(18)
  const [maximum, setMaximum] = useState(28)
  const [domains, setDomains] = useState("gmail.com")
  const inFlight = useRef(false)
  const apply = (next: RegistrationStatus) => {
    setJob(next)
    useAccountsRun.setState({
      registrationCurrent: next,
      registrationPollError: null,
    })
    if (next.account_saved) void refreshAccounts()
  }
  const check = async () => {
    try {
      apply(await registrationStatus())
      setLoaded(true)
      setError("")
    } catch {
      setError(
        t("Не удалось проверить задание. Создание аккаунта не повторялось")
      )
    }
  }
  useEffect(() => {
    let active = true
    void Promise.allSettled([
      registrationCapabilities(),
      registrationStatus(),
      registrationHistory(),
    ]).then(([available, current, previous]) => {
      if (!active) return
      setCapChecked(true)
      if (previous.status === "fulfilled" && !useAccountsRun.getState().run)
        useAccountsRun
          .getState()
          .setRegistrationResults(previous.value.results.slice().reverse())
      if (available.status === "fulfilled") setCaps(available.value)
      if (current.status === "fulfilled") {
        setJob(current.value)
        setLoaded(true)
        if (current.value.account_saved) void refreshAccounts()
      }
      if (available.status === "rejected" || current.status === "rejected")
        setError(t("Не удалось проверить доступность регистрации"))
    })
    return () => {
      active = false
    }
  }, [])
  const shownJob =
    current && (!job.scope || current.scope === job.scope) ? current : job
  useEffect(() => {
    if (run?.kind === "register" || !registrationPolling(shownJob)) return
    let active = true
    let checking = false
    const timer = window.setInterval(() => {
      if (checking) return
      checking = true
      void registrationStatus()
        .then((next) => {
          if (!active) return
          if (
            next.job_id !== shownJob.job_id ||
            (shownJob.scope && next.scope !== shownJob.scope)
          ) {
            setError(t("Сервер или задание изменились. Очередь остановлена"))
            return
          }
          apply(next)
          setError("")
          if (next.account_saved) void refreshAccounts()
        })
        .catch(() => {
          if (active)
            setError(
              t(
                "Не удалось проверить задание. Создание аккаунта не повторялось"
              )
            )
        })
        .finally(() => {
          checking = false
        })
    }, 2_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [shownJob, run?.kind])
  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (
      inFlight.current ||
      !loaded ||
      registrationBusy(job) ||
      !modeAvailable(caps, mode)
    )
      return
    if (!validCount || !count) {
      setError(t("Укажите количество от 1 до 50"))
      return
    }
    if (caps?.geo_policy !== "proxy_auto_v1") {
      setError(t("Сервер ещё не поддерживает автоматическую географию прокси"))
      return
    }
    if (run) {
      setError(t("Дождитесь завершения текущей очереди"))
      return
    }
    if (
      !pool?.enabled ||
      !pool.health.some((row) => row.registration && row.enabled !== false)
    ) {
      setError(t("Выберите прокси для регистрации в разделе «Прокси»"))
      return
    }
    inFlight.current = true
    setError("")
    startRun(
      "register",
      Array.from({ length: count }, (_, index) =>
        t("Регистрация {0}", [index + 1])
      ),
      1,
      {
        registration: {
          mode,
          anymessage_token: token,
          age_min: minimum,
          age_max: maximum,
          domains: domains.split(/[,\s]+/).filter(Boolean),
          expected_scope: shownJob.scope,
        },
      }
    )
    setToken("")
    inFlight.current = false
  }
  const cancel = async () => {
    if (run?.kind === "register") requestStop()
    if (inFlight.current) return
    inFlight.current = true
    setPending(true)
    try {
      apply(await cancelRegistration())
    } catch {
      setError(t("Отмена не подтверждена. Проверьте состояние задания"))
    } finally {
      inFlight.current = false
      setPending(false)
    }
  }
  const busy = pending || registrationBusy(shownJob) || !!run
  const autoGeo = caps?.geo_policy === "proxy_auto_v1"

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <SheetContent className="gap-0">
        <SheetHeader>
          <SheetTitle>{t("Создать аккаунт")}</SheetTitle>
          <SheetDescription>
            {t(
              "Созданный аккаунт и его сессия сохранятся в списке автоматически"
            )}
          </SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4">
          <p role="status" className="text-sm">
            {t(
              shownJob.status === "idle" && (!loaded || !capChecked)
                ? "Проверка доступности регистрации"
                : STATUS[shownJob.status]
            )}
            {shownJob.username ? ` · @${shownJob.username}` : ""}
          </p>
          {shownJob.username_selection &&
          shownJob.username_selection.requested ? (
            <Alert>
              <AlertDescription>
                {t(
                  (
                    {
                      confirmed: "Выбранное имя подтверждено",
                      unavailable:
                        "Желаемое имя занято или недоступно. Аккаунт сохранён с фактическим именем",
                      rejected:
                        "TikTok отклонил желаемое имя. Аккаунт и вход сохранены",
                      blocked:
                        "Выбор имени остановлен проверкой TikTok. Аккаунт и вход сохранены",
                      unknown:
                        "Выбор имени не подтверждён. Не повторяйте создание аккаунта",
                      skipped: "TikTok пропустил выбор имени. Аккаунт сохранён",
                    } as Record<string, string>
                  )[shownJob.username_selection.status] ??
                    "Выбор имени не подтверждён. Не повторяйте создание аккаунта"
                )}
              </AlertDescription>
            </Alert>
          ) : null}
          {shownJob.reason ? (
            <Alert>
              <AlertDescription>{t(shownJob.reason)}</AlertDescription>
            </Alert>
          ) : null}
          {error || pollError ? (
            <Alert variant="destructive">
              <AlertDescription>{error || pollError}</AlertDescription>
            </Alert>
          ) : null}
          {shownJob.billing_status === "unknown" ? (
            <Alert>
              <AlertDescription>
                {t(
                  "Аккаунт сохранён. Списание требует проверки; не повторяйте регистрацию"
                )}
              </AlertDescription>
            </Alert>
          ) : null}
          {capChecked &&
          !caps?.modes.some((row) => row.supported && row.available) ? (
            <p className="text-sm text-muted-foreground">
              {t("Регистрация сейчас недоступна на сервере")}
            </p>
          ) : null}
          {run?.kind === "register" ? (
            <Alert>
              <AlertDescription>
                {t("Очередь регистрации: {0} из {1}", [run.done, run.total])}
                <Button
                  type="button"
                  variant="outline"
                  disabled={run.stopping}
                  onClick={requestStop}
                >
                  {t(
                    run.stopping
                      ? "Останавливаем очередь"
                      : "Остановить после текущего"
                  )}
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}
          {results.length ? (
            <div
              className="flex flex-col gap-2"
              aria-label={t("Результаты регистрации")}
            >
              {results.map((result, index) => (
                <p key={result.job_id ?? index} className="text-sm">
                  {index + 1}.{" "}
                  {result.username
                    ? `@${result.username}`
                    : t("Аккаунт не подтверждён")}{" "}
                  · {t(STATUS[result.status])}
                  {result.email_domain ? ` · ${result.email_domain}` : ""}
                  {result.reason ? ` · ${t(result.reason)}` : ""}
                </p>
              ))}
            </div>
          ) : null}
          <form
            onSubmit={submit}
            autoComplete="off"
            className="flex flex-col gap-4"
          >
            <FieldGroup>
              <Field data-invalid={!validCount}>
                <FieldLabel htmlFor="registration-count">
                  {t("Количество")}
                </FieldLabel>
                <NumberInput
                  id="registration-count"
                  value={quantity}
                  onValueChange={setQuantity}
                  disabled={busy}
                  aria-invalid={!validCount}
                />
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Аккаунты регистрируются по одному. При ограничении или неизвестном результате очередь остановится"
                  )}
                </p>
              </Field>
              <Field>
                <FieldLabel>{t("Прокси и география")}</FieldLabel>
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Выбирается живой наименее занятый прокси с отметкой для регистрации. Страну определяет сервер по фактическому маршруту"
                  )}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    onClose()
                    navigate("/proxies")
                  }}
                >
                  {t("Настроить прокси")}
                </Button>
                {!autoGeo ? (
                  <p role="status" className="text-sm text-muted-foreground">
                    {t(
                      "Ожидается поддержка автоматической географии на сервере"
                    )}
                  </p>
                ) : null}
              </Field>

              <Field>
                <FieldLabel>{t("Режим регистрации")}</FieldLabel>
                <SimpleSelect
                  aria-label={t("Режим регистрации")}
                  value={String(mode)}
                  disabled={busy || !capChecked}
                  onValueChange={(value) => {
                    const selected = Number(value)
                    if (selected === 3 || selected === 4) setMode(selected)
                  }}
                  items={([1, 2, 3, 4] as const).map((number) => {
                    const capability = caps?.modes.find(
                      (row) => row.mode === number
                    )
                    const available =
                      number >= 3 &&
                      capability?.supported === true &&
                      capability.available === true
                    const reason = available
                      ? undefined
                      : t(
                          number === 2
                            ? "Реальная регистрация в этом режиме недоступна"
                            : capability?.supported !== true
                              ? "Режим пока не поддерживается сервером"
                              : "Режим сейчас недоступен на сервере"
                        )
                    return {
                      value: String(number),
                      label: ["Low", "Medium", "High", "Max"][number - 1],
                      disabled: !available,
                      reason,
                    }
                  })}
                />
              </Field>

              <Field>
                <FieldLabel htmlFor="registration-mail">
                  {t("Ключ AnyMessage")}
                </FieldLabel>
                <Input
                  id="registration-mail"
                  type="password"
                  autoComplete="off"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  disabled={busy}
                  required
                />
              </Field>

              <Field>
                <FieldLabel htmlFor="registration-min">
                  {t("Возраст от")}
                </FieldLabel>
                <Input
                  id="registration-min"
                  type="number"
                  min={18}
                  max={120}
                  value={minimum}
                  onChange={(event) => setMinimum(Number(event.target.value))}
                  disabled={busy}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="registration-max">
                  {t("Возраст до включительно")}
                </FieldLabel>
                <Input
                  id="registration-max"
                  type="number"
                  min={minimum}
                  max={120}
                  value={maximum}
                  onChange={(event) => setMaximum(Number(event.target.value))}
                  disabled={busy}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="registration-domains">
                  {t("Домены почты через запятую")}
                </FieldLabel>
                <p className="text-sm text-muted-foreground">
                  {t(
                    "Выберите до четырёх доменов. Для каждого аккаунта первый выбирается случайно; следующий — только если сервис явно сообщил, что почт нет. Отправитель писем фиксирован"
                  )}
                </p>
                <Input
                  id="registration-domains"
                  value={domains}
                  onChange={(event) => setDomains(event.target.value)}
                  disabled={busy}
                  required
                />
              </Field>
            </FieldGroup>
            <div className="flex flex-wrap gap-2">
              <Button
                type="submit"
                disabled={
                  busy ||
                  !loaded ||
                  !validCount ||
                  !autoGeo ||
                  !modeAvailable(caps, mode)
                }
              >
                {pending || !capChecked ? <Spinner /> : null}
                {t("Начать регистрацию ({0})", [count ?? 0])}
              </Button>
              {registrationPolling(shownJob) ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={pending}
                  onClick={cancel}
                >
                  {t("Отменить регистрацию")}
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                disabled={pending}
                onClick={() => void check()}
              >
                {t("Проверить задание")}
              </Button>
            </div>
          </form>
        </div>
      </SheetContent>
    </Sheet>
  )
}
