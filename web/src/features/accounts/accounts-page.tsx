import { useLanguage } from "@/lib/i18n"
import { useEffect, useMemo, useRef, useState } from "react"
import {
  BanIcon,
  CheckCheckIcon,
  Columns3Icon,
  EyeOffIcon,
  LogInIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchXIcon,
  UsersRoundIcon,
} from "lucide-react"

import {
  disableAccounts,
  purgeAccount,
  refreshAccounts,
  restoreAccount,
  startProfilesRefresh,
  useAccounts,
  useAvatars,
  useProfilesRefresh,
  usePurgeStatus,
} from "@/api/accounts"
import { isCampaignLive, useCampaignStatus } from "@/api/campaign"
import { useStudioCounters } from "@/api/studio"
import { sectionTitle } from "@/app/sections"
import { useSettings } from "@/api/misc"
import { useCampaignLauncher } from "@/features/campaign/launcher"
import { confirm, confirmDestructive } from "@/components/confirm"
import { Hint } from "@/components/hint"
import { Page, PageBody, PageHeader } from "@/components/page"
import { SearchInput } from "@/components/search-input"
import { ErrorView, LoadingRows, StateView } from "@/components/state-view"
import { toneText, type Tone } from "@/components/status"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useHotkey } from "@/hooks/use-hotkey"
import { openExternal, tiktokProfileUrl } from "@/lib/native"
import { fmtInt } from "@/lib/format"
import { notify } from "@/lib/notify"
import { cn } from "@/lib/utils"

import type { RowHandlers } from "./account-row"
import { AccountSheet } from "./account-sheet"
import { AccountsBar } from "./accounts-bar"
import {
  ACCOUNT_ACTIONS,
  actionContext,
  type AccountRowActions,
  type SelectionActions,
  type SelectionTarget,
} from "./actions"
import { AccountsTable } from "./accounts-table"
import { COLUMNS, gridTemplate, useTier, visibleColumns } from "./columns"
import { AddPanel } from "./add-panel"
import { BannedBlock } from "./banned-block"
import {
  startRun,
  useAccountsRun,
  type RunKind,
  type RunOptions,
} from "./accounts-run"
import { EditPanel } from "./edit-panel"
import { useAccountsView } from "./accounts-view"
import {
  filterAccounts,
  filterCounts,
  searchByName,
  sortAccounts,
  type AccountsFilter,
} from "./filter"
import {
  ACCOUNTS_LABEL,
  ACC_CONFIRM,
  ACC_TOAST,
  EMPTY_LABEL,
  FILTER_LABEL,
  HEAD_ACTION,
} from "./labels"
import { copyUsernames, selectedUsernames } from "./username"

/* Экран аккаунтов: таблица во всю ширину со срезами-вкладками, поиском,
   сортировкой и выбором колонок; выбор строк флажками, массовые действия
   поверх выделения, карточка аккаунта сбоку по клику на строку. Прогон
   очереди не зависит от того, открыт ли экран. Страница не скроллится —
   прокрутка внутри таблицы.

   Публикации в шапке нет: запуск по всем аккаунтам живёт на своём экране,
   рядом с формой. Здесь публикация — это выбор аккаунтов: строкой или
   выделением. */

/* Переключатель в диалоге: «Перед удалением выйти», «Сменить устройство».
   Выключен при открытии; выбор уходит в onChange, а не в состояние экрана:
   диалог живёт своей жизнью в ConfirmHost, значение читается уже после
   того, как confirm() разрешится. */
function OptionSwitch({
  label,
  onChange,
}: {
  label: string
  onChange: (v: boolean) => void
}) {
  const [checked, setChecked] = useState(false)
  return (
    <label className="mt-3 flex items-center gap-2 text-sm">
      <Switch
        checked={checked}
        onCheckedChange={(v) => {
          setChecked(v)
          onChange(v)
        }}
      />
      {label}
    </label>
  )
}

/** Выбор переключателя — в поле current: его читают после confirm(). */
const into = (box: { current: boolean }) => (v: boolean) => {
  box.current = v
}

/** Текст диалога и под ним — «Сменить устройство». */
function withNewDevice(text: string, box: { current: boolean }) {
  return (
    <>
      {text}
      <OptionSwitch label={ACC_CONFIRM.newDevice} onChange={into(box)} />
    </>
  )
}

export default function AccountsPage() {
  useLanguage()
  const accountsQuery = useAccounts()
  const avatars = useAvatars()
  // числа студии есть только у аккаунтов со входом: без аккаунтов не спрашиваем
  const counters = useStudioCounters(!!accountsQuery.data?.accounts.length).data
  const settings = useSettings()
  const camp = useCampaignStatus()
  const profiles = useProfilesRefresh()
  const purge = usePurgeStatus()
  const { launch } = useCampaignLauncher()

  const filter = useAccountsView((s) => s.filter)
  const search = useAccountsView((s) => s.query)
  const sort = useAccountsView((s) => s.sort)
  const dir = useAccountsView((s) => s.dir)
  const setFilter = useAccountsView((s) => s.setFilter)
  const setSort = useAccountsView((s) => s.setSort)
  const setQuery = useAccountsView((s) => s.setQuery)
  const selected = useAccountsView((s) => s.selected)
  const select = useAccountsView((s) => s.select)
  const selectAll = useAccountsView((s) => s.selectAll)
  const clearSelection = useAccountsView((s) => s.clearSelection)
  const pruneSelection = useAccountsView((s) => s.pruneSelection)
  const card = useAccountsView((s) => s.card)
  const setCard = useAccountsView((s) => s.setCard)
  // карточка — часть этого экрана: ушли с него — при возврате она закрыта
  useEffect(() => () => setCard(null), [setCard])
  const hiddenList = useAccountsView((s) => s.hidden)
  const toggleColumn = useAccountsView((s) => s.toggleColumn)
  const hidden = useMemo(() => new Set(hiddenList), [hiddenList])
  const tier = useTier()

  const run = useAccountsRun((s) => s.run)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)

  const accounts = useMemo(
    () => accountsQuery.data?.accounts ?? [],
    [accountsQuery.data]
  )
  const banned = useMemo(
    () => accountsQuery.data?.banned ?? [],
    [accountsQuery.data]
  )
  const campOn = isCampaignLive(camp.data)
  const profilesRunning = !!profiles.data?.running
  const threads = settings.data?.threads ?? 1

  // выделение не должно переживать удаление своих строк
  useEffect(() => {
    pruneSelection(accounts.map((a) => a.username))
  }, [accounts, pruneSelection])

  // чистки кончились — счётчик постов в строках обновится не сам
  const purgeWasBusy = useRef(false)
  useEffect(() => {
    const busyNow = !!purge.data?.current.length
    if (purgeWasBusy.current && !busyNow) void refreshAccounts()
    purgeWasBusy.current = busyNow
  }, [purge.data])

  const visibleAccounts = useMemo(
    () =>
      sortAccounts(
        searchByName(filterAccounts(accounts, filter), search),
        sort,
        dir,
        counters
      ),
    [accounts, filter, search, sort, dir, counters]
  )
  const visibleBanned = useMemo(
    () => searchByName(banned, search),
    [banned, search]
  )
  const usernames = useMemo(
    () => visibleAccounts.map((a) => a.username),
    [visibleAccounts]
  )
  /* Пробелы за запрос не считаем: поиск их и так игнорирует, а пустое состояние
     не должно говорить «ничего не найдено» из-за случайного пробела. */
  const seeking = search.trim().length > 0

  /* Спиннер на строке: своё действие, прогон, профили, чистка или публикация.
     Имён тут единицы, и набор нужен только на отрисовку — считаем каждый раз
     заново: мемо с Set, уходящим пропом, компилятор React сохранять не берётся,
     а выгоды от него всё равно нет.

     У публикации в спиннер идут аккаунты из живых воркеров (camp.data.workers),
     а не весь остаток очереди: очередь на большой кампании —
     это все аккаунты разом, ещё не дошедшие до своего воркера, и с ней спиннер
     стоял бы у всего списка на весь прогон, хотя обрабатываются только
     workers.length штук одновременно — ровно столько, сколько задано потоков. */
  const workingNow = isCampaignLive(camp.data) ? (camp.data?.workers ?? []) : []
  const busyNames = new Set<string>([
    ...(run?.current ?? []),
    ...(profiles.data?.running
      ? [...(profiles.data.current ?? []), ...(profiles.data.pending ?? [])]
      : []),
    ...(purge.data?.current ?? []),
    ...workingNow.map((w) => w.account),
  ])

  const counts = useMemo(
    () => filterCounts(accounts, banned),
    [accounts, banned]
  )
  /* Срезы — вкладками-видами. «Готовы» и «Все» стоят всегда: без них не с
     чего начать; остальные — когда в них кто-то есть (или срез открыт). */
  const tabs = (Object.keys(FILTER_LABEL) as AccountsFilter[])
    .filter((value) => value === "all" || value === "ready" || counts[value] || value === filter)
    .map((value) => ({
      value,
      label: FILTER_LABEL[value],
      count: counts[value],
      tone: (value === "banned" ? "bad" : value === "nologin" || value === "shadow" ? "warn" : undefined) as
        | Tone
        | undefined,
    }))

  const chosen = useMemo(
    () => accounts.filter((a) => selected.has(a.username)),
    [accounts, selected]
  )
  const chosenNames = useMemo(() => chosen.map((a) => a.username), [chosen])
  const editingAccount = useMemo(
    () =>
      editing ? (accounts.find((a) => a.username === editing) ?? null) : null,
    [accounts, editing]
  )
  const chosenPending = chosen
    .filter((a) => !a.has_session)
    .map((a) => a.username)
  const chosenPurgeable = chosen
    .filter((a) => a.has_session)
    .map((a) => a.username)
  const chosenLoggedIn = chosen
    .filter((a) => a.has_session)
    .map((a) => a.username)
  const cardAccount = useMemo(
    () => (card ? (accounts.find((a) => a.username === card) ?? null) : null),
    [accounts, card]
  )
  /* Что попадёт в буфер: то же выделение, что считает панель и берут соседние
     действия, — иначе после смены среза копировалось бы меньше обещанного.
     Видимые строки идут в порядке экрана, скрытые срезом или поиском — следом. */
  const pickedNames = useMemo(
    () => selectedUsernames(selected, usernames, chosenNames),
    [selected, usernames, chosenNames]
  )

  /* ── действия ─────────────────────────────────────────────────────── */

  const refreshProfiles = (usernames?: string[]) => {
    startProfilesRefresh(usernames).catch((error) =>
      notify.error(error, ACC_TOAST.notRefreshed)
    )
  }

  async function runMany(
    kind: RunKind,
    queue: string[],
    ask: {
      title: string
      description?: React.ReactNode
      confirmText: string
      destructive?: boolean
    },
    // функция, не значение: переключатель в description меняется уже внутри
    // открытого диалога, и опции нужно читать после confirm(), а не до
    getOpts?: () => RunOptions
  ) {
    if (!queue.length) return
    const ok = await confirm(ask)
    if (ok) startRun(kind, queue, threads, getOpts?.())
  }

  const loginAll = () => {
    const queue = accounts.filter((a) => !a.has_session).map((a) => a.username)
    return runMany("login", queue, {
      title: ACC_CONFIRM.loginAll(queue.length),
      description: ACC_CONFIRM.loginDesc(queue.length),
      confirmText: ACC_CONFIRM.loginAllYes,
    })
  }

  const restore = async (username: string) => {
    try {
      await restoreAccount(username)
      notify.ok(ACC_TOAST.restored(username))
    } catch (error) {
      notify.error(error, ACC_TOAST.notRestored)
    } finally {
      void refreshAccounts()
    }
  }

  /* Отключение обратимо — вместо окна подтверждения тост с «Отменить»:
     отключённые возвращаются в список тем же путём, что и «Вернуть» в срезе
     отключённых. Окно на каждое обратимое действие приучает жать «Да» не
     читая. */
  const disable = async (usernames: string[]) => {
    try {
      const res = await disableAccounts(usernames)
      const gone = res.disabled
      notify.ok(ACC_TOAST.disabled(gone.length), {
        duration: 8000,
        action: gone.length
          ? {
              label: ACC_TOAST.undo,
              onClick: () => {
                void Promise.allSettled(gone.map((u) => restoreAccount(u))).then((all) => {
                  const back = all.filter((r) => r.status === "fulfilled").length
                  if (back === gone.length) notify.ok(ACC_TOAST.undone(back))
                  else notify.error(ACC_TOAST.notRestored)
                  void refreshAccounts()
                })
              },
            }
          : undefined,
      })
    } catch (error) {
      notify.error(error, ACC_TOAST.notDisabled)
    } finally {
      void refreshAccounts()
    }
  }

  const rowActions: AccountRowActions = {
    publish: (username) => void launch([username]),
    refresh: (username) => refreshProfiles([username]),
    login: (username) => startRun("login", [username], 1),
    open: (username) => void openExternal(tiktokProfileUrl(username)),
    copy: (username) => void copyUsernames([username]),
    edit: (username) => setEditing(username),
    purge: async (username) => {
      const ok = await confirmDestructive({
        title: ACC_CONFIRM.purgeOne(username),
        description: ACC_CONFIRM.purgeDesc,
        confirmText: ACC_CONFIRM.purgeYes,
      })
      if (!ok) return
      try {
        await purgeAccount(username)
        notify.ok(ACC_TOAST.purging(username))
      } catch (error) {
        notify.error(error, ACC_TOAST.notPurged)
      }
    },
    clearSession: async (username) => {
      const newDevice = { current: false }
      const ok = await confirm({
        title: ACC_CONFIRM.clearSessionOne(username),
        description: withNewDevice(ACC_CONFIRM.clearSessionDesc, newDevice),
        confirmText: ACC_CONFIRM.clearSessionYes,
      })
      if (ok)
        startRun("clearSession", [username], 1, {
          newDevice: newDevice.current,
        })
    },
    logout: async (username) => {
      const newDevice = { current: false }
      const ok = await confirm({
        title: ACC_CONFIRM.logoutOne(username),
        description: withNewDevice(ACC_CONFIRM.logoutDesc, newDevice),
        confirmText: ACC_CONFIRM.logoutYes,
      })
      if (ok)
        startRun("logout", [username], 1, { newDevice: newDevice.current })
    },
    disable: (username) => void disable([username]),
    remove: async (username) => {
      const hasSession = accounts.find(
        (a) => a.username === username
      )?.has_session
      const logoutFirst = { current: false }
      const newDevice = { current: false }
      const ok = await confirmDestructive({
        title: ACC_CONFIRM.deleteOne(username),
        description: (
          <>
            {ACC_CONFIRM.deleteDesc}
            {hasSession ? (
              <OptionSwitch
                label={ACC_CONFIRM.deleteLogoutFirst}
                onChange={into(logoutFirst)}
              />
            ) : null}
            <OptionSwitch
              label={ACC_CONFIRM.newDevice}
              onChange={into(newDevice)}
            />
          </>
        ),
        confirmText: ACC_CONFIRM.deleteYes,
      })
      if (ok)
        startRun("delete", [username], 1, {
          logoutFirst: logoutFirst.current,
          newDevice: newDevice.current,
        })
    },
  }

  /* Обработчики строк — одни и те же между отрисовками: строка обёрнута в
     memo, и каждое событие прогона иначе перерисовывало бы весь видимый
     список. Сами действия берутся из свежего рендера через ссылку. */
  const live = useRef({ rowActions, usernames })
  useEffect(() => {
    live.current = { rowActions, usernames }
  })
  const handlers = useMemo<RowHandlers>(
    () => ({
      actions: Object.fromEntries(
        ACCOUNT_ACTIONS.map((a) => [a.key, (username: string) => live.current.rowActions[a.key](username)])
      ) as AccountRowActions,
      onOpen: (username) => setCard(username),
      onPick: (username, mode) => select(username, mode, live.current.usernames),
      /** правым кликом по невыделенной строке выделение переходит на неё одну */
      onContextSelect: (username) => select(username, "solo", live.current.usernames),
    }),
    [select, setCard]
  )

  /* Панель над выделением и правый клик по выделенной строке — одно и то же
     действие над одним и тем же набором. Собираем его здесь один раз: заведи
     мы его дважды, панель и меню разошлись бы либо аккаунтами, либо тем, что
     делают. Ключи — из SELECTION_ACTIONS, того же списка, что рисует кнопки. */
  const selectionActions: SelectionActions = {
    publish: () => void launch(chosenNames),
    refresh: () => refreshProfiles(chosenNames),
    copy: () => void copyUsernames(pickedNames),
    login: () =>
      void runMany("login", chosenPending, {
        title: ACC_CONFIRM.loginMany(chosenPending.length),
        description: ACC_CONFIRM.loginDesc(chosenPending.length),
        confirmText: ACC_CONFIRM.loginYes,
      }),
    purge: () =>
      void runMany("purge", chosenPurgeable, {
        title: ACC_CONFIRM.purgeMany(chosenPurgeable.length),
        description: ACC_CONFIRM.purgeManyDesc,
        confirmText: ACC_CONFIRM.purgeYes,
        destructive: true,
      }),
    clearSession: () => {
      const newDevice = { current: false }
      void runMany(
        "clearSession",
        chosenLoggedIn,
        {
          title: ACC_CONFIRM.clearSessionMany(chosenLoggedIn.length),
          description: withNewDevice(ACC_CONFIRM.clearSessionDesc, newDevice),
          confirmText: ACC_CONFIRM.clearSessionYes,
        },
        () => ({ newDevice: newDevice.current })
      )
    },
    logout: () => {
      const newDevice = { current: false }
      void runMany(
        "logout",
        chosenLoggedIn,
        {
          title: ACC_CONFIRM.logoutMany(chosenLoggedIn.length),
          description: withNewDevice(ACC_CONFIRM.logoutDesc, newDevice),
          confirmText: ACC_CONFIRM.logoutYes,
        },
        () => ({ newDevice: newDevice.current })
      )
    },
    disable: () => void disable(chosenNames),
    remove: () => {
      const logoutFirst = { current: false }
      const newDevice = { current: false }
      void runMany(
        "delete",
        chosenNames,
        {
          title: ACC_CONFIRM.deleteMany(chosenNames.length),
          description: (
            <>
              {ACC_CONFIRM.deleteDesc}
              {chosenLoggedIn.length ? (
                <OptionSwitch
                  label={ACC_CONFIRM.deleteLogoutFirst}
                  onChange={into(logoutFirst)}
                />
              ) : null}
              <OptionSwitch
                label={ACC_CONFIRM.newDevice}
                onChange={into(newDevice)}
              />
            </>
          ),
          confirmText: ACC_CONFIRM.deleteYes,
          destructive: true,
        },
        () => ({
          logoutFirst: logoutFirst.current,
          newDevice: newDevice.current,
        })
      )
    },
  }
  const selectionCtx = actionContext(chosen, { locked: campOn })
  const selection: SelectionTarget = {
    ctx: selectionCtx,
    run: (key) => selectionActions[key](),
  }

  useHotkey("Escape", clearSelection, {
    inInputs: false,
    // открытую карточку Esc закрывает сам — выделение под ней не трогаем
    enabled: selected.size > 0 && !card,
  })
  useHotkey("Mod+A", () => selectAll(usernames), {
    inInputs: false,
    preventDefault: true,
    enabled: usernames.length > 0,
  })

  /* ── список ───────────────────────────────────────────────────────── */

  /* Пустой поиск чистит только поиск, срез оставляет: сбросить заодно и срез —
     значит выбросить человека в другой список, которого он не просил. */
  const clearSearch = () => setQuery("")

  /* Пусто бывает по-разному, и человеку каждый раз нужен свой следующий шаг:
     в «Готовы» — войти, в «Без входа» и «В тени» пусто — это хорошо. */
  const emptyView = () => {
    /* Аккаунтов нет вовсе — тут нечего смотреть ни в одном срезе, и звать надо
       за добавлением, а не показывать «в этом срезе пусто». Проверяем это
       раньше среза: иначе новичок на старте (а старт — срез «Готовы») читал бы
       «Готовых аккаунтов нет» вместо «Аккаунтов пока нет».

       Отдельный случай — все аккаунты отключены: живой список пуст, но это не
       «аккаунтов нет», и человеку нужен срез отключённых, а не добавление. */
    if (!accounts.length && filter !== "banned") {
      if (banned.length) {
        return (
          <StateView
            icon={BanIcon}
            title={EMPTY_LABEL.allBanned}
            text={EMPTY_LABEL.allBannedText}
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFilter("banned")}
              >
                {FILTER_LABEL.banned}
              </Button>
            }
          />
        )
      }
      return (
        <StateView
          icon={UsersRoundIcon}
          title={EMPTY_LABEL.none}
          action={
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              <PlusIcon />
              {EMPTY_LABEL.add}
            </Button>
          }
        />
      )
    }
    if (seeking) {
      return (
        <StateView
          icon={SearchXIcon}
          title={EMPTY_LABEL.notFound}
          action={
            <Button variant="outline" size="sm" onClick={clearSearch}>
              {EMPTY_LABEL.clearSearch}
            </Button>
          }
        />
      )
    }
    if (filter === "banned") {
      return (
        <StateView
          icon={BanIcon}
          title={EMPTY_LABEL.banned}
          text={EMPTY_LABEL.bannedText}
        />
      )
    }
    if (filter === "nologin") {
      return (
        <StateView
          icon={CheckCheckIcon}
          title={EMPTY_LABEL.nologin}
          text={EMPTY_LABEL.nologinText}
        />
      )
    }
    if (filter === "shadow") {
      return (
        <StateView
          icon={EyeOffIcon}
          title={EMPTY_LABEL.shadow}
          text={EMPTY_LABEL.shadowText}
        />
      )
    }
    if (filter === "ready") {
      /* Пусто в «Готовы» по двум причинам: не вошли или посты в тени. Сначала
         предлагаем вход — если он нужен хоть кому-то, начинать надо с него;
         когда со входом порядок, значит дело в тенях, и ведём туда. */
      const shadowed = counts.shadow > 0
      return (
        <StateView
          icon={UsersRoundIcon}
          title={EMPTY_LABEL.ready}
          text={EMPTY_LABEL.readyText}
          action={
            counts.nologin ? (
              <Button
                variant="outline"
                size="sm"
                disabled={campOn}
                onClick={loginAll}
              >
                <LogInIcon />
                {HEAD_ACTION.loginAll}
              </Button>
            ) : shadowed ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setFilter("shadow")}
              >
                {EMPTY_LABEL.showShadow}
              </Button>
            ) : null
          }
        />
      )
    }
    /* Сюда попасть нельзя: «Все» без поиска всегда что-то показывает, а
       остальные срезы разобраны выше. Если однажды логика разъедется, лучше
       пустая панель с выходом, чем просто пустая панель. */
    return (
      <StateView
        icon={SearchXIcon}
        title={EMPTY_LABEL.notFound}
        action={
          <Button variant="outline" size="sm" onClick={clearSearch}>
            {EMPTY_LABEL.clearSearch}
          </Button>
        }
      />
    )
  }

  const bannedView = filter === "banned"
  const rows = bannedView ? visibleBanned.length : visibleAccounts.length
  const columns = visibleColumns(tier, hidden)
  const template = gridTemplate(
    columns,
    tier,
    visibleAccounts.some((a) => !a.has_session)
  )

  let list: React.ReactNode
  if (accountsQuery.data === undefined && accountsQuery.isError) {
    list = (
      <ErrorView
        error={accountsQuery.error}
        onRetry={() => void accountsQuery.refetch()}
      />
    )
  } else if (accountsQuery.data === undefined) {
    list = <LoadingRows />
  } else if (!rows) {
    list = emptyView()
  } else if (bannedView) {
    list = (
      <BannedBlock
        banned={visibleBanned}
        avatars={avatars.data}
        disabled={campOn}
        onRestore={(u) => void restore(u)}
        padBottom={!!run || selected.size > 0}
      />
    )
  } else {
    list = (
      <AccountsTable
        accounts={visibleAccounts}
        avatars={avatars.data}
        counters={counters}
        busyNames={busyNames}
        locked={campOn}
        selected={selected}
        sort={sort}
        dir={dir}
        onSort={setSort}
        columns={columns}
        template={template}
        handlers={handlers}
        selection={selection}
        onPickAll={(all) => (all ? selectAll(usernames) : clearSelection())}
        padBottom={!!run || selected.size > 0}
      />
    )
  }

  return (
    <Page fill className="relative">
      <PageHeader
        title={sectionTitle("accounts")}
        toolbar={
          <Tabs value={filter} onValueChange={(v) => setFilter(v as AccountsFilter)} className="-mb-3">
            <TabsList aria-label={ACCOUNTS_LABEL.filters}>
              {tabs.map((t) => (
                <TabsTrigger key={t.value} value={t.value}>
                  {t.label}
                  <span className={cn("tabular text-xs", t.count && t.tone ? toneText[t.tone] : "text-muted-foreground")}>
                    {fmtInt(t.count)}
                  </span>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
        search={<SearchInput value={search} onValueChange={setQuery} placeholder={ACCOUNTS_LABEL.search} />}
        actions={
          <>
            {/* Обновление профилей и вход работают с живым списком: в срезе
                отключённых их нет, и кнопки там только сбивали бы с толку. */}
            {bannedView ? null : (
              <>
                <DropdownMenu>
                  <Hint label={ACCOUNTS_LABEL.columns}>
                    <DropdownMenuTrigger
                      render={<Button variant="outline" size="icon" aria-label={ACCOUNTS_LABEL.columns} className="hidden md:inline-flex" />}
                    >
                      <Columns3Icon />
                    </DropdownMenuTrigger>
                  </Hint>
                  <DropdownMenuContent align="end" className="min-w-48">
                    <DropdownMenuGroup>
                      <DropdownMenuLabel>{ACCOUNTS_LABEL.columns}</DropdownMenuLabel>
                      {COLUMNS.map((c) => (
                        <DropdownMenuCheckboxItem
                          key={c.key}
                          checked={!hidden.has(c.key)}
                          disabled={c.tier > tier}
                          onCheckedChange={() => toggleColumn(c.key)}
                        >
                          {c.label}
                        </DropdownMenuCheckboxItem>
                      ))}
                    </DropdownMenuGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
                {/* во время обновления кнопка живая: аккаунты, которых нет в
                    очереди, просто добавятся к идущему прогону */}
                <Hint label={profilesRunning ? HEAD_ACTION.refreshing : HEAD_ACTION.refresh}>
                  <Button
                    variant="outline"
                    size="icon"
                    disabled={!accounts.length}
                    onClick={() => refreshProfiles()}
                    aria-label={profilesRunning ? HEAD_ACTION.refreshing : HEAD_ACTION.refresh}
                  >
                    {profilesRunning ? <Spinner /> : <RefreshCwIcon />}
                  </Button>
                </Hint>
                {counts.nologin ? (
                  <Button variant="outline" disabled={campOn} onClick={loginAll} aria-label={HEAD_ACTION.loginAll}>
                    <LogInIcon />
                    <span className="hidden md:inline">{HEAD_ACTION.loginAll}</span>
                  </Button>
                ) : null}
              </>
            )}
            <Button onClick={() => setAdding(true)}>
              <PlusIcon />
              {HEAD_ACTION.add}
            </Button>
          </>
        }
      />
      <PageBody bleed>
        {list}
        {adding ? <AddPanel onClose={() => setAdding(false)} /> : null}
        {editingAccount ? <EditPanel account={editingAccount} onClose={() => setEditing(null)} /> : null}
      </PageBody>
      <AccountSheet
        account={cardAccount}
        avatar={card ? avatars.data?.[card] : undefined}
        counters={counters}
        busy={!!card && busyNames.has(card)}
        locked={campOn}
        actions={rowActions}
        onClose={() => setCard(null)}
      />
      <AccountsBar ctx={selectionCtx} actions={selectionActions} onClear={clearSelection} />
    </Page>
  )
}
