import { t, useLanguage } from "@/lib/i18n"
import { userMessage } from "@/api/client"
import { useState } from "react"

import { saveLicenseKey, useLicense, useLicenseHistory } from "@/api/license"
import type { LicenseCharge, LicenseInfo } from "@/api/types"
import { sectionTitle } from "@/app/sections"
import { Page, PageBody, PageHeader } from "@/components/page"
import { Panel } from "@/components/panel"
import { UserAvatar } from "@/components/user-avatar"
import { ErrorView, QueryView } from "@/components/state-view"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { fmtDateTime, fmtDec, fmtSigned, sentence } from "@/lib/format"
import { notify } from "@/lib/notify"

import { PROFILE_LABEL, PROFILE_STATUS } from "./labels"

/* Профиль: ключ к нашему серверу, баланс и история списаний. Сам сервер
   спрашивает бэкенд программы (modules/remote.py) — интерфейс адреса не знает. */

const at = (ts: number | null | undefined) =>
  ts ? fmtDateTime(new Date(ts * 1000).toISOString()) : "—"

const pad = (n: number) => String(n).padStart(2, "0")
const hm = (ts: number) => {
  const d = new Date(ts * 1000)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** «Сегодня» / «Вчера» / «24.09» — заголовок дня в истории. */
function dayLabel(ts: number, now = new Date()): string {
  const d = new Date(ts * 1000)
  const start = (x: Date) =>
    new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((start(now) - start(d)) / 86_400_000)
  if (days === 0) return PROFILE_LABEL.today
  if (days === 1) return PROFILE_LABEL.yesterday
  const date = `${pad(d.getDate())}.${pad(d.getMonth() + 1)}`
  return d.getFullYear() === now.getFullYear()
    ? date
    : `${date}.${d.getFullYear()}`
}

/** Юзернейм — с собакой; пачка профилей («u1, u2 +3») — как есть. */
const who = (account: string) =>
  /^[\w.]+$/.test(account) ? `@${account}` : account

/** Сумма со знаком у ненулевых движений — видно, расход это или приход;
    бесплатное действие («0 — бесплатно») — без знака, знак у нуля не значит
    ничего. */
const money = (it: LicenseCharge, currency: string) => {
  if (it.amount == null) return "—"
  const signed = it.kind === "credit" ? it.amount : -it.amount
  return `${fmtSigned(signed)} ${currency}`
}

export default function ProfilePage() {
  useLanguage()
  const query = useLicense()
  return (
    <Page>
      <PageHeader title={sectionTitle("profile")} />
      <PageBody width="narrow">
        <QueryView query={query}>
          {(info) => (
            <>
              <KeyPanel info={info} />
              {info.status === "active" || info.status === "disabled" ? (
                <HistoryPanel currency={info.currency || "₽"} />
              ) : null}
            </>
          )}
        </QueryView>
      </PageBody>
    </Page>
  )
}

function KeyPanel({ info }: { info: LicenseInfo }) {
  useLanguage()
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)
  const status = PROFILE_STATUS[info.status] ?? {
    text: info.status,
    variant: "secondary" as const,
  }

  const save = async (key: string) => {
    setBusy(true)
    try {
      await saveLicenseKey(key)
      setValue("")
      notify.ok(key ? PROFILE_LABEL.saved : PROFILE_LABEL.removed)
    } catch (error) {
      notify.error(error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel bodyClassName="gap-5">
      <div className="flex flex-col gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <UserAvatar
            url={info.avatar_url}
            name={info.name || PROFILE_LABEL.profile}
            size="lg"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-lg font-semibold">
              {info.name || PROFILE_LABEL.profile}
            </p>
            {info.key ? (
              <p className="text-xs text-muted-foreground">
                {PROFILE_LABEL.key} {info.key}
              </p>
            ) : null}
          </div>
          <Badge variant={status.variant}>{status.text}</Badge>
        </div>
        {info.status === "active" || info.status === "disabled" ? (
          <div className="flex flex-wrap items-end gap-3 rounded-lg bg-muted/50 p-4">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-xs text-muted-foreground">
                {PROFILE_LABEL.balance}
              </span>
              <span className="text-2xl font-semibold tabular">
                {info.balance == null ? "—" : fmtDec(info.balance)}{" "}
                <span className="text-sm font-normal text-muted-foreground">
                  {info.currency}
                </span>
              </span>
            </div>
            {info.expires_at ? (
              <span className="text-xs text-muted-foreground tabular">
                {PROFILE_LABEL.until} {at(info.expires_at)}
              </span>
            ) : null}
          </div>
        ) : null}
        {info.error ? (
          <p className="text-sm text-destructive">
            {sentence(userMessage(info.error))}
          </p>
        ) : null}
        <form
          className="border-t pt-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (value.trim()) void save(value.trim())
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="license-key">
                {info.key ? PROFILE_LABEL.replaceKey : PROFILE_LABEL.key}
              </FieldLabel>
              <Input
                id="license-key"
                type="password"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="submit" disabled={busy || !value.trim()}>
                {busy ? <Spinner /> : null}
                {PROFILE_LABEL.save}
              </Button>
              {info.key ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void save("")}
                >
                  {PROFILE_LABEL.remove}
                </Button>
              ) : null}
            </div>
          </FieldGroup>
        </form>
      </div>
    </Panel>
  )
}

function HistoryPanel({ currency }: { currency: string }) {
  useLanguage()
  const query = useLicenseHistory(true)
  const items: LicenseCharge[] = query.data?.pages.flatMap((p) => p.items) ?? []
  // строки уже новые первыми: день пишется над первой строкой каждого дня
  const days = items.map((it) => dayLabel(it.at))

  return (
    <Panel title={PROFILE_LABEL.history}>
      {query.isPending ? (
        <Spinner className="mx-auto" />
      ) : query.isError ? (
        <ErrorView error={query.error} onRetry={() => void query.refetch()} />
      ) : !items.length ? (
        <p className="text-sm text-muted-foreground">{PROFILE_LABEL.empty}</p>
      ) : (
        <div className="flex flex-col">
          <ul className="flex flex-col text-sm">
            {items.map((it, i) => (
              <li key={`${it.at}-${i}`} className="border-b last:border-0">
                {i === 0 || days[i] !== days[i - 1] ? (
                  <div
                    className={
                      "pb-1 text-xs font-medium text-muted-foreground" +
                      (i ? " pt-3" : "")
                    }
                  >
                    {days[i]}
                  </div>
                ) : null}
                <div className="flex items-start gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="font-medium">
                        {t(it.title || it.action)}
                      </span>
                      {it.ok ? null : (
                        <span className="text-xs text-destructive">
                          {PROFILE_LABEL.failed}
                        </span>
                      )}
                    </div>
                    <div className="text-xs break-words text-muted-foreground">
                      {[
                        it.account ? who(it.account) : "",
                        it.note,
                        it.ok ? "" : userMessage(it.error),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end">
                    <span
                      className={
                        "tabular" +
                        (it.kind === "credit" ? " text-success" : "")
                      }
                    >
                      {money(it, currency)}
                    </span>
                    <span className="text-xs text-muted-foreground tabular">
                      {hm(it.at)}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {query.hasNextPage ? (
            <Button
              variant="ghost"
              size="sm"
              className="mt-2 self-center"
              disabled={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              {query.isFetchingNextPage ? <Spinner /> : null}
              {PROFILE_LABEL.more}
            </Button>
          ) : null}
        </div>
      )}
    </Panel>
  )
}
