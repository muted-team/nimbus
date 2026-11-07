import { t, useLanguage } from "@/lib/i18n"
import { userMessage } from "@/api/client"
import { useMemo, useRef } from "react"
import {
  BadgeCheckIcon,
  EllipsisIcon,
  LockIcon,
  MailIcon,
  ShieldCheckIcon,
  UserRoundIcon,
  type LucideIcon,
} from "lucide-react"

import { useCampaignStatus } from "@/api/campaign"
import { useLogs } from "@/api/logs"
import type { Account, StudioCountersMap } from "@/api/types"
import { Flag } from "@/components/flag"
import { StatusBadge, StatusDot } from "@/components/status"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { RESULT_LABEL } from "@/features/campaign/labels"
import { outcomeOf } from "@/features/campaign/report"
import { logKey } from "@/features/logs/log-filter"
import { LogRow } from "@/features/logs/log-row"
import { fmtAgo, fmtCompact, fmtInt } from "@/lib/format"
import { cn } from "@/lib/utils"

import { AccountActionItems } from "./action-items"
import { accountAction, actionContext, type AccountActionKey, type AccountRowActions } from "./actions"
import { ACCOUNT_ACTION, CARD_LABEL, COLUMN_LABEL, HAS_EMAIL, HAS_TOTP, PRIVATE, VERIFIED } from "./labels"
import { rowNumbers } from "./studio"
import { atUsername } from "./username"

/* Карточка аккаунта сбоку: всё, что в строке таблицы не поместилось, без
   ухода со страницы. Профиль и метки (галочка, закрытый, чем входит), числа
   профиля и студии, его строка в итоге прогона, его строки журнала и
   действия — те же пункты, что в меню строки. */

const MAIN: AccountActionKey[] = ["publish", "refresh", "open"]
const MORE = ["copy", "edit", "purge", "clearSession", "logout", "disable", "remove"] as const
const LOG_LIMIT = 20

export function AccountSheet({
  account,
  avatar,
  counters,
  busy,
  locked,
  actions,
  onClose,
}: {
  account: Account | null
  avatar?: string
  counters?: StudioCountersMap
  busy: boolean
  locked: boolean
  actions: AccountRowActions
  onClose: () => void
}) {
  const panel = useRef<HTMLDivElement>(null)
  return (
    <Sheet open={!!account} onOpenChange={(open) => (open ? null : onClose())}>
      {/* Фокус — сама панель, а не первая кнопка в ней: иначе открытие мышью
          рисовало рамку на «Обновить», будто до неё дошли Tab'ом. С клавиатуры
          — как обычно, на первую кнопку. Вернуть фокус при закрытии некуда:
          строка его не берёт, и он уезжал на последнюю кнопку с фокусом
          (меню профиля) — после Esc она светилась рамкой. */}
      <SheetContent
        ref={panel}
        className="w-full gap-0 p-0 outline-none sm:max-w-md"
        initialFocus={(type) => (type === "keyboard" ? true : panel.current)}
        finalFocus={false}
      >
        {account ? (
          <SheetBody account={account} avatar={avatar} counters={counters} busy={busy} locked={locked} actions={actions} />
        ) : null}
      </SheetContent>
    </Sheet>
  )
}

function SheetBody({
  account,
  avatar,
  counters,
  busy,
  locked,
  actions,
}: {
  account: Account
  avatar?: string
  counters?: StudioCountersMap
  busy: boolean
  locked: boolean
  actions: AccountRowActions
}) {
  useLanguage()
  const u = account.username
  const p = account.profile
  const studio = counters?.[u]
  const numbers = rowNumbers(account, counters)
  const ctx = actionContext([account], { locked, busy })
  const { data: st } = useCampaignStatus()
  const result = st?.results.find((r) => r.account === u)
  const events = useLogs((s) => s.events)
  const log = useMemo(() => events.filter((e) => e.account === u && !e.debug).slice(0, LOG_LIMIT), [events, u])

  const marks: { icon: LucideIcon; text: string; tone?: string }[] = []
  if (p?.verified) marks.push({ icon: BadgeCheckIcon, text: t(VERIFIED), tone: "text-info" })
  if (p?.private_account) marks.push({ icon: LockIcon, text: t(PRIVATE) })
  if (account.has_totp) marks.push({ icon: ShieldCheckIcon, text: t(HAS_TOTP) })
  if (account.has_email) marks.push({ icon: MailIcon, text: t(HAS_EMAIL) })

  const stats: [string, number | null | undefined][] = [
    [COLUMN_LABEL.followers, numbers.followers],
    [COLUMN_LABEL.likes, p?.likes],
    [COLUMN_LABEL.views, p?.posts?.views],
    [COLUMN_LABEL.posts, numbers.posts],
    [COLUMN_LABEL.shadow, p?.posts?.shadow],
    [CARD_LABEL.visitors, numbers.visitors],
    [CARD_LABEL.privatePosts, studio?.private_posts],
    [CARD_LABEL.following, studio?.following],
  ]

  const login = accountAction("login")
  const main = [...(account.has_session ? [] : (["login"] as AccountActionKey[])), ...MAIN].map(accountAction)

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <SheetHeader className="gap-3 border-b p-4 pr-12">
        <div className="flex items-center gap-3">
          <Avatar className="size-12 shrink-0">
            {avatar ? <AvatarImage src={avatar} alt="" /> : null}
            <AvatarFallback>
              <UserRoundIcon className="size-5 text-muted-foreground" />
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <SheetTitle className="truncate select-text">{atUsername(u)}</SheetTitle>
            <SheetDescription className="flex items-center gap-2 truncate">
              {p?.nickname ? <span className="truncate">{p.nickname}</span> : null}
              {account.region ? <Flag code={account.region} /> : null}
            </SheetDescription>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={account.has_session ? "ok" : "warn"}>
            {account.has_session ? CARD_LABEL.session : CARD_LABEL.noSession}
          </StatusBadge>
          {marks.map((m) => (
            <span key={m.text} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <m.icon className={cn("size-3.5", m.tone)} />
              {m.text}
            </span>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {main.map((a) => (
            <Button
              key={a.key}
              variant={a.key === login.key ? "default" : "outline"}
              size="sm"
              disabled={a.disabled(ctx)}
              onClick={() => actions[a.key](u)}
            >
              <a.icon />
              {a.label(ctx)}
            </Button>
          ))}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={ACCOUNT_ACTION.more} />}>
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-44">
              <AccountActionItems
                keys={MORE}
                ctx={ctx}
                run={(key) => actions[key](u)}
                Item={DropdownMenuItem}
                Separator={DropdownMenuSeparator}
              />
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </SheetHeader>

      <Section title={CARD_LABEL.numbers}>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
          {stats.map(([label, value]) => (
            <div key={label} className="flex min-w-0 flex-col gap-1">
              <dt className="truncate text-xs text-muted-foreground">{label}</dt>
              <dd className={cn("text-base tabular", !value && "text-muted-foreground")}>{fmtCompact(value)}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-muted-foreground">
          {COLUMN_LABEL.fetched} {fmtAgo(p?.fetched_at)}
        </p>
      </Section>

      {result && st ? (
        <Section title={CARD_LABEL.lastRun}>
          <div className="flex items-center gap-3 text-sm">
            <StatusBadge tone={RESULT_LABEL[outcomeOf(result, st.posts_per_account)].tone}>
              {RESULT_LABEL[outcomeOf(result, st.posts_per_account)].text}
            </StatusBadge>
            <span className="text-muted-foreground tabular">
              {CARD_LABEL.posts(fmtInt(result.posts_done), fmtInt(st.posts_per_account))}
            </span>
          </div>
          {result.reason ? <p className="text-sm text-muted-foreground select-text">{userMessage(result.reason)}</p> : null}
        </Section>
      ) : null}

      <Section title={CARD_LABEL.log} flush>
        {log.length ? (
          log.map((item, i) => <LogRow key={logKey(item, i)} item={item} hideAccount />)
        ) : (
          <p className="flex items-center gap-2 px-4 pb-4 text-sm text-muted-foreground">
            <StatusDot tone="neutral" />
            {CARD_LABEL.logEmpty}
          </p>
        )}
      </Section>
    </div>
  )
}

function Section({ title, flush, children }: { title: string; flush?: boolean; children: React.ReactNode }) {
  return (
    <section className={cn("flex flex-col gap-3 border-b py-4 last:border-0", !flush && "px-4")}>
      <h3 className={cn("text-xs text-muted-foreground", flush && "px-4")}>{title}</h3>
      {children}
    </section>
  )
}
