import { useLanguage } from "@/lib/i18n"
import { useEffect, useMemo, useState } from "react"
import {
  CopyIcon,
  GlobeIcon,
  LogInIcon,
  PlusIcon,
  PowerIcon,
  PowerOffIcon,
  RefreshCwIcon,
  SearchXIcon,
  SendIcon,
  ServerOffIcon,
  Trash2Icon,
} from "lucide-react"

import { rotateProxy, saveProxies, useProxies } from "@/api/proxies"
import { sectionTitle } from "@/app/sections"
import { confirmDestructive } from "@/components/confirm"
import { Hint } from "@/components/hint"
import { Page, PageBody, PageHeader } from "@/components/page"
import { SearchInput } from "@/components/search-input"
import { SelectionBar, type BarAction } from "@/components/selection-bar"
import { toneText, type Tone } from "@/components/status"
import { ErrorView, LoadingRows, StateView } from "@/components/state-view"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useHotkey } from "@/hooks/use-hotkey"
import { fmtInt } from "@/lib/format"
import { copyWithToast } from "@/lib/native"
import { notify } from "@/lib/notify"
import { emptySelection, pick, prune, type PickMode, type SelectionState } from "@/lib/selection"
import { cn } from "@/lib/utils"

import {
  defaultDir,
  filterCounts,
  filterProxies,
  isEnabled,
  loginIndexes,
  publishIndexes,
  offIndexes,
  searchProxies,
  sortProxies,
  toProxyRows,
  type ProxiesFilter,
  type SortDir,
  type SortKey,
} from "./filter"
import { autoCheckAllowed } from "./health"
import {
  EMPTY_LABEL,
  FILTER_LABEL,
  NOSHADOW_LABEL,
  PROXIES_LABEL,
  PROXY_BULK,
  PROXIES_TOAST,
  PROXY_CONFIRM,
  rotateOutcome,
} from "./labels"
import { ProxiesTable } from "./proxies-table"
import {
  checkProxiesNow,
  indexesAfterRemoval,
  saveProxiesLines,
  useProxiesStore,
} from "./proxies-store"
import { patchNoshadow, readNoshadow, writeNoshadow } from "./noshadow"
import { NoshadowPanel } from "./noshadow-panel"
import { ProxyAddPanel } from "./proxy-add-panel"
import { ProxyCapacity } from "./proxy-capacity"
import { ProxyEditPanel } from "./proxy-edit-panel"
import type { ProxyRowActions } from "./proxy-row"

/* Экран прокси: таблица во всю ширину со срезами-вкладками, поиском и
   сортировкой по заголовку.
   Список хранит сервер, а не черновик поля — каждая правка строки (правка,
   удаление, добавление) уходит сама, явным действием человека. Вставка
   пачкой текстом — отдельное действие «Добавить», а не главное место экрана. */

export default function ProxiesPage() {
  useLanguage()
  const query = useProxies()
  const checking = useProxiesStore((s) => s.checking)
  const autoCheckedAt = useProxiesStore((s) => s.autoCheckedAt)

  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<ProxiesFilter>("all")
  const [sort, setSort] = useState<SortKey>("index")
  const [dir, setDir] = useState<SortDir>("asc")
  const [adding, setAdding] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  /* панель noshadow: null — закрыта, [] — собрать новые, номера — правка выбранных */
  const [noshadow, setNoshadow] = useState<number[] | null>(null)
  const [rotateBusy, setRotateBusy] = useState<number | null>(null)
  const [selection, setSelection] = useState<SelectionState<number>>(emptySelection)

  const rows = useMemo(
    () => (query.data ? toProxyRows(query.data.health, query.data.proxies) : []),
    [query.data]
  )
  const counts = useMemo(() => filterCounts(rows), [rows])
  const visible = useMemo(
    () => sortProxies(searchProxies(filterProxies(rows, filter), search), sort, dir),
    [rows, filter, search, sort, dir]
  )
  const seeking = search.trim().length > 0

  /* Выбор — номера строк по всему списку. Строк, которых больше нет, в нём не
     считаем; после удаления номера съезжают, поэтому любое удаление выбор
     снимает целиком. */
  const alive = useMemo(() => rows.map((r) => r.index), [rows])
  const selected = useMemo(() => prune(selection, alive).selected, [selection, alive])
  const chosen = rows.filter((r) => selected.has(r.index))
  const order = visible.map((r) => r.index)
  const onPick = (index: number, mode: PickMode) => setSelection((s) => pick(s, index, mode, order))
  const clearSelection = () => setSelection(emptySelection())
  const selectAll = () => setSelection({ selected: new Set(order), anchor: null, rangeBase: null })
  useHotkey("Escape", clearSelection, { inInputs: false, enabled: selected.size > 0 && !adding && editingIndex == null && noshadow == null })
  useHotkey("Mod+A", selectAll, { inInputs: false, enabled: order.length > 0 })

  const onSort = (key: SortKey) => {
    if (key === sort) {
      setDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSort(key)
      setDir(defaultDir(key))
    }
  }

  const check = () => void checkProxiesNow()
  useHotkey("Mod+Enter", check, { enabled: rows.length > 0 && !checking })

  /* Раздел открыли, а вердикты старые или их нет — проверка идёт сама; повтор
     не чаще раза в минуту. Список к этому моменту уже на сервере (правка
     строки сохраняется сама, черновика поля тут больше нет) — достаточно
     самой проверки, пересылать список заново незачем. */
  useEffect(() => {
    const health = query.data?.health
    if (!health?.length || !autoCheckAllowed(health, autoCheckedAt)) return
    useProxiesStore.setState({ autoCheckedAt: Date.now() })
    void checkProxiesNow({ silent: true })
  }, [query.data, autoCheckedAt])

  const toggleUse = (enabled: boolean) => {
    saveProxies({ enabled }).catch((error) => notify.error(error))
  }

  const rowActions: ProxyRowActions = {
    edit: (index) => setEditingIndex(index),
    remove: async (index) => {
      const addr = rows.find((r) => r.index === index)?.proxy ?? ""
      const ok = await confirmDestructive({
        title: PROXY_CONFIRM.deleteOne(addr),
        description: PROXY_CONFIRM.deleteDesc,
        confirmText: PROXY_CONFIRM.deleteYes,
      })
      if (!ok || !query.data) return
      const next = query.data.proxies.filter((_, i) => i !== index)
      const login = indexesAfterRemoval(loginIndexes(rows), index)
      const publish = indexesAfterRemoval(publishIndexes(rows), index)
      const off = indexesAfterRemoval(offIndexes(rows), index)
      try {
        // next пуст — это и есть явное «удалить последнюю строку» (T-201)
        const res = await saveProxiesLines(next, {
          allowEmpty: next.length === 0,
          login,
          publish,
          off,
        })
        if (res) notify.ok(PROXIES_TOAST.deleted(addr))
        setSelection(emptySelection())
      } catch (error) {
        notify.error(error, PROXIES_TOAST.notDeleted)
      }
    },
    rotate: async (index) => {
      setRotateBusy(index)
      try {
        const res = await rotateProxy(index)
        const outcome = rotateOutcome(res)
        if (outcome.ok) notify.ok(outcome.text)
        else notify.warn(outcome.text)
      } catch (error) {
        notify.error(error, PROXIES_TOAST.notRotated)
      } finally {
        setRotateBusy(null)
      }
    },
    renew: async (index) => {
      const n = query.data ? readNoshadow(query.data.proxies[index] ?? "") : null
      if (!query.data || !n) return
      const next = [...query.data.proxies]
      next[index] = writeNoshadow(patchNoshadow(n, { renew: true }))
      const addr = rows.find((r) => r.index === index)?.proxy ?? ""
      try {
        await saveProxiesLines(next, { login: loginIndexes(rows), publish: publishIndexes(rows), off: offIndexes(rows) })
        notify.ok(PROXIES_TOAST.renewed(addr))
      } catch (error) {
        notify.error(error, PROXIES_TOAST.notChanged)
      }
    },
    /* Отметки «выключена», «вход» и «публикация» — номера строк по ВСЕМУ списку (`rows`,
       он строится из data.health целиком, до срезов и поиска), а не по
       видимому куску экрана: иначе строки, скрытые фильтром, потеряли бы
       свою отметку при следующей отправке. */
    toggleEnabled: async (index) => {
      const target = rows.find((r) => r.index === index)
      if (!target) return
      const wasEnabled = isEnabled(target)
      const off = offIndexes(rows)
      const next = wasEnabled ? [...off, index] : off.filter((i) => i !== index)
      try {
        await saveProxies({ off: next })
        notify.ok(wasEnabled ? PROXIES_TOAST.disabled(target.proxy) : PROXIES_TOAST.enabled(target.proxy))
      } catch (error) {
        notify.error(error, PROXIES_TOAST.notToggled)
      }
    },
    toggleLogin: async (index, checked) => {
      const login = loginIndexes(rows)
      const next = checked ? [...login, index] : login.filter((i) => i !== index)
      try {
        await saveProxies({ login: next })
      } catch (error) {
        notify.error(error, PROXIES_TOAST.notLogin)
      }
    },
    togglePublish: async (index, checked) => {
      const publish = publishIndexes(rows)
      const next = checked ? [...publish, index] : publish.filter((i) => i !== index)
      try {
        await saveProxies({ publish: next })
      } catch (error) {
        notify.error(error, PROXIES_TOAST.notPublish)
      }
    },
  }

  /* Удалить несколько строк разом (мёртвые, выбранные). Отметки остальных
     строк пересчитываются с конца, чтобы номера не съезжали от уже убранных;
     после удаления номера съезжают — выбор снимается целиком. */
  const removeIndexes = async (indexes: number[], title: string) => {
    if (!query.data || !indexes.length) return
    const ok = await confirmDestructive({
      title,
      description: PROXY_CONFIRM.deleteDesc,
      confirmText: PROXY_CONFIRM.deleteYes,
    })
    if (!ok) return
    const gone = new Set(indexes)
    const next = query.data.proxies.filter((_, i) => !gone.has(i))
    let login = loginIndexes(rows)
    let publish = publishIndexes(rows)
    let off = offIndexes(rows)
    for (const index of [...indexes].sort((a, b) => b - a)) {
      login = indexesAfterRemoval(login, index)
      publish = indexesAfterRemoval(publish, index)
      off = indexesAfterRemoval(off, index)
    }
    try {
      const res = await saveProxiesLines(next, { allowEmpty: next.length === 0, login, publish, off })
      if (res) notify.ok(PROXIES_TOAST.deletedMany(indexes.length))
      clearSelection()
      return true
    } catch (error) {
      notify.error(error, PROXIES_TOAST.notDeleted)
      return false
    }
  }

  /* Мёртвые — пачкой: по одной их удалять долго, а держать незачем. */
  const removeDead = async () => {
    const dead = rows.filter((r) => r.state === "dead").map((r) => r.index)
    if (await removeIndexes(dead, PROXY_CONFIRM.deleteDead(dead.length))) setFilter("all")
  }

  /* Действия над выбранными — те же, что у строки, только пачкой. Отметки
     считаются по всему списку, как и у одиночных: скрытые срезом строки
     своих отметок не теряют. */
  const setMarks = async (patch: { off?: number[]; login?: number[]; publish?: number[] }, done?: string) => {
    try {
      await saveProxies(patch)
      if (done) notify.ok(done)
    } catch (error) {
      notify.error(error, PROXIES_TOAST.notToggled)
    }
  }
  const union = (a: number[], b: number[]) => [...new Set([...a, ...b])]
  const minus = (a: number[], b: Set<number>) => a.filter((i) => !b.has(i))
  const chosenIdx = chosen.map((r) => r.index)

  const removeChosen = () =>
    void removeIndexes(chosenIdx, PROXY_CONFIRM.deleteMany(chosenIdx.length))

  const copyChosen = () =>
    copyWithToast(chosen.map((r) => r.proxy).join("\n"), PROXIES_TOAST.copied(chosen.length))

  const anyOn = chosen.some((r) => isEnabled(r))
  const chosenNoshadow = chosen.filter((r) => r.noshadow).map((r) => r.index)
  const anyOff = chosen.some((r) => !isEnabled(r))
  const bulk: BarAction[] = [
    ...(anyOn
      ? [{
          key: "disable",
          label: PROXY_BULK.disable,
          icon: PowerOffIcon,
          onClick: () => void setMarks({ off: union(offIndexes(rows), chosenIdx) }, PROXIES_TOAST.disabledMany(chosenIdx.length)),
        }]
      : []),
    ...(anyOff
      ? [{
          key: "enable",
          label: PROXY_BULK.enable,
          icon: PowerIcon,
          onClick: () => void setMarks({ off: minus(offIndexes(rows), selected) }, PROXIES_TOAST.enabledMany(chosenIdx.length)),
        }]
      : []),
    { key: "copy", label: PROXY_BULK.copy, icon: CopyIcon, onClick: () => void copyChosen() },
    { key: "login-on", label: PROXY_BULK.loginOn, icon: LogInIcon, onClick: () => void setMarks({ login: union(loginIndexes(rows), chosenIdx) }) },
    { key: "login-off", label: PROXY_BULK.loginOff, icon: LogInIcon, onClick: () => void setMarks({ login: minus(loginIndexes(rows), selected) }) },
    { key: "publish-on", label: PROXY_BULK.publishOn, icon: SendIcon, onClick: () => void setMarks({ publish: union(publishIndexes(rows), chosenIdx) }) },
    { key: "publish-off", label: PROXY_BULK.publishOff, icon: SendIcon, onClick: () => void setMarks({ publish: minus(publishIndexes(rows), selected) }) },
    ...(chosenNoshadow.length
      ? [{ key: "noshadow", label: NOSHADOW_LABEL.bulk, icon: GlobeIcon, onClick: () => setNoshadow(chosenNoshadow) }]
      : []),
    { key: "remove", label: PROXY_BULK.remove, icon: Trash2Icon, destructive: true, separatorBefore: true, onClick: removeChosen },
  ]

  const tabs = (Object.keys(FILTER_LABEL) as ProxiesFilter[])
    .filter((value) => value === "all" || counts[value] || value === filter)
    .map((value) => ({
      value,
      label: FILTER_LABEL[value],
      count: counts[value],
      tone: (value === "dead" ? "bad" : value === "unchecked" ? "warn" : undefined) as Tone | undefined,
    }))

  const clearSearch = () => setSearch("")

  const emptyView = () => {
    if (!rows.length) {
      return (
        <StateView
          icon={ServerOffIcon}
          title={EMPTY_LABEL.none}
          action={
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              <PlusIcon />
              {PROXIES_LABEL.add}
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
    return (
      <StateView
        icon={SearchXIcon}
        title={EMPTY_LABEL.emptySlice}
        action={
          <Button variant="outline" size="sm" onClick={() => setFilter("all")}>
            {FILTER_LABEL.all}
          </Button>
        }
      />
    )
  }

  const editingAddr = editingIndex != null ? rows.find((r) => r.index === editingIndex)?.proxy ?? "" : ""

  let list: React.ReactNode
  if (query.data === undefined && query.isError) {
    list = <ErrorView error={query.error} onRetry={() => void query.refetch()} />
  } else if (query.data === undefined) {
    list = <LoadingRows />
  } else if (!visible.length) {
    list = emptyView()
  } else {
    list = (
      <ProxiesTable
        rows={visible}
        fetchedAt={query.dataUpdatedAt}
        sort={sort}
        dir={dir}
        onSort={onSort}
        rotateBusy={rotateBusy}
        actions={rowActions}
        marked={{ login: loginIndexes(rows).length, publish: publishIndexes(rows).length }}
        selected={selected}
        onPick={onPick}
        onPickAll={(all) => (all ? selectAll() : clearSelection())}
        bulk={bulk}
      />
    )
  }

  return (
    <Page fill className="relative">
      <PageHeader
        title={sectionTitle("proxies")}
        toolbar={
          <Tabs value={filter} onValueChange={(v) => setFilter(v as ProxiesFilter)} className="-mb-3">
            <TabsList aria-label={PROXIES_LABEL.filters}>
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
        search={<SearchInput value={search} onValueChange={setSearch} placeholder={PROXIES_LABEL.search} />}
        actions={
          query.data ? (
            <>
              <div className="flex items-center gap-2">
                <Switch id="proxies-use" checked={query.data.enabled} onCheckedChange={toggleUse} />
                <Label htmlFor="proxies-use">{PROXIES_LABEL.use}</Label>
              </div>
              {filter === "dead" && counts.dead ? (
                <Button variant="destructive" onClick={() => void removeDead()}>
                  <Trash2Icon />
                  {PROXIES_LABEL.removeDead}
                </Button>
              ) : null}
              <Hint label={checking ? PROXIES_LABEL.checking : PROXIES_LABEL.check} hotkey="Mod+Enter">
                <Button
                  variant="outline"
                  size="icon"
                  disabled={!rows.length || checking}
                  onClick={check}
                  aria-label={checking ? PROXIES_LABEL.checking : PROXIES_LABEL.check}
                >
                  {checking ? <Spinner /> : <RefreshCwIcon />}
                </Button>
              </Hint>
              <Button onClick={() => setAdding(true)}>
                <PlusIcon />
                {PROXIES_LABEL.add}
              </Button>
            </>
          ) : null
        }
      />
      <PageBody bleed>
        {query.data ? (
          <div className="flex flex-col gap-4 border-b px-4 py-4 md:px-6">
            <ProxyCapacity data={query.data} />
            {adding ? (
              <ProxyAddPanel
                proxies={query.data.proxies}
                login={loginIndexes(rows)}
                publish={publishIndexes(rows)}
                off={offIndexes(rows)}
                onClose={() => setAdding(false)}
                onNoshadow={() => {
                  setAdding(false)
                  setNoshadow([])
                }}
              />
            ) : null}
          </div>
        ) : null}
        {list}
      </PageBody>
      <SelectionBar
        count={chosen.length}
        actions={bulk}
        main={bulk.findIndex((a) => a.key === "copy") + 1}
        onClear={clearSelection}
      />
      {noshadow != null && query.data ? (
        <NoshadowPanel
          proxies={query.data.proxies}
          marks={{ login: loginIndexes(rows), publish: publishIndexes(rows), off: offIndexes(rows) }}
          editing={noshadow.length ? noshadow : undefined}
          onClose={() => {
            setNoshadow(null)
            if (noshadow.length) clearSelection()
          }}
        />
      ) : null}
      {editingIndex != null && query.data ? (
        <ProxyEditPanel
          index={editingIndex}
          addr={editingAddr}
          proxies={query.data.proxies}
          login={loginIndexes(rows)}
          publish={publishIndexes(rows)}
          off={offIndexes(rows)}
          onClose={() => setEditingIndex(null)}
        />
      ) : null}
    </Page>
  )
}
