import { useLanguage } from "@/lib/i18n"
import { useEffect, useMemo, useState } from "react"
import {
  PlusIcon,
  RefreshCwIcon,
  SearchXIcon,
  ServerOffIcon,
  Trash2Icon,
} from "lucide-react"

import { rotateProxy, saveProxies, useProxies } from "@/api/proxies"
import { sectionTitle } from "@/app/sections"
import { confirmDestructive } from "@/components/confirm"
import { Hint } from "@/components/hint"
import { Page, PageBody, PageHeader } from "@/components/page"
import { SearchInput } from "@/components/search-input"
import { SelectionBar } from "@/components/selection-bar"
import { toneText, type Tone } from "@/components/status"
import { ErrorView, LoadingRows, StateView } from "@/components/state-view"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useHotkey } from "@/hooks/use-hotkey"
import { useNow } from "@/hooks/use-now"
import { fmtInt, sentence } from "@/lib/format"
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
  registrationIndexes,
  offIndexes,
  searchProxies,
  sortProxies,
  toProxyRows,
  type ProxiesFilter,
  type ProxyRow,
  type SortDir,
  type SortKey,
} from "./filter"
import { autoCheckAllowed, canRotate, nowTickMs } from "./health"
import { proxyActions, type ProxyActionKey } from "./actions"
import {
  EMPTY_LABEL,
  FILTER_LABEL,
  PROXIES_LABEL,
  PROXIES_TOAST,
  PROXY_CONFIRM,
  rotateOutcome,
} from "./labels"
import { ProxiesTable } from "./proxies-table"
import {
  checkProxiesNow,
  indexesAfterRemoval,
  mutateProxies,
  proxyListCurrent,
  saveProxiesLines,
  useProxiesStore,
} from "./proxies-store"
import { patchNoshadow, readNoshadow, writeNoshadow } from "./noshadow"
import { NoshadowPanel } from "./noshadow-panel"
import { ProxyAddPanel } from "./proxy-add-panel"
import { ProxyCapacity } from "./proxy-capacity"
import { ProxyEditPanel } from "./proxy-edit-panel"
import { parseProxyLine } from "./proxy-line"
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
  const mutating = useProxiesStore((s) => s.mutating)

  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState<ProxiesFilter>("all")
  const [sort, setSort] = useState<SortKey>("index")
  const [dir, setDir] = useState<SortDir>("asc")
  const [adding, setAdding] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  /* панель noshadow: null — закрыта, [] — собрать новые, номера — правка выбранных */
  const [noshadow, setNoshadow] = useState<number[] | null>(null)
  const [rotateBusy, setRotateBusy] = useState<Set<number>>(() => new Set())
  const [selection, setSelection] = useState<SelectionState<number>>(emptySelection)

  const rows = useMemo(
    () => (query.data ? toProxyRows(query.data.health, query.data.proxies) : []),
    [query.data]
  )
  const now = useNow(nowTickMs(rows))
  const elapsed = query.dataUpdatedAt ? Math.max(0, Math.floor((now - query.dataUpdatedAt) / 1000)) : 0
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
    if (!query.data) return
    mutateProxies(query.data.proxies, () => saveProxies({ enabled })).catch((error) => notify.error(error))
  }

  const rotate = (targets: ProxyRow[]) => mutateProxies(query.data?.proxies ?? [], async () => {
    const ready = targets.filter((r) => isEnabled(r) && canRotate(r, elapsed))
    setRotateBusy(new Set(ready.map((r) => r.index)))
    for (const { index } of ready) {
      if (!proxyListCurrent(query.data?.proxies ?? [])) break
      try {
        const res = await rotateProxy(index)
        const outcome = rotateOutcome(res)
        if (outcome.ok) notify.ok(outcome.text)
        else notify.warn(outcome.text)
      } catch (error) {
        notify.error(error, PROXIES_TOAST.notRotated)
      } finally {
        setRotateBusy((busy) => new Set([...busy].filter((i) => i !== index)))
      }
    }
    setRotateBusy(new Set())
  })

  const renew = (targets: ProxyRow[]) => mutateProxies(query.data?.proxies ?? [], async () => {
    if (!query.data) return
    const indexes = new Set(targets.filter((r) => isEnabled(r) && r.noshadow && r.noshadow.minutes > 0).map((r) => r.index))
    if (!indexes.size) return
    if (query.data.proxies.some((line, index) => !indexes.has(index) && !parseProxyLine(line))) {
      notify.warn(PROXIES_TOAST.notChanged)
      return
    }
    const next = query.data.proxies.map((line, index) => {
      const n = indexes.has(index) ? readNoshadow(line) : null
      return n ? writeNoshadow(patchNoshadow(n, { renew: true })) : line
    })
    try {
      const res = await saveProxiesLines(next, { login: loginIndexes(rows), publish: publishIndexes(rows), registration: registrationIndexes(rows), off: offIndexes(rows) })
      const error = res?.errors?.[0]?.error
      if (error) {
        notify.warn(sentence(error))
        return
      }
      if (res) notify.ok(targets.length === 1 ? PROXIES_TOAST.renewed(targets[0].proxy) : PROXIES_TOAST.changed(indexes.size))
    } catch (error) {
      notify.error(error, PROXIES_TOAST.notChanged)
    }
  })

  /* Удалить несколько строк разом (мёртвые, выбранные). Отметки остальных
     строк пересчитываются с конца, чтобы номера не съезжали от уже убранных;
     после удаления номера съезжают — выбор снимается целиком. */
  const removeIndexes = (indexes: number[], title: string) => mutateProxies(query.data?.proxies ?? [], async () => {
    if (!query.data || !indexes.length) return
    try {
      const ok = await confirmDestructive({
        title,
        description: PROXY_CONFIRM.deleteDesc,
        confirmText: PROXY_CONFIRM.deleteYes,
      })
      if (!ok || !proxyListCurrent(query.data.proxies)) return
      const gone = new Set(indexes)
      const next = query.data.proxies.filter((_, i) => !gone.has(i))
      let login = loginIndexes(rows)
      let publish = publishIndexes(rows)
      let registration = registrationIndexes(rows)
      let off = offIndexes(rows)
      for (const index of [...indexes].sort((a, b) => b - a)) {
        login = indexesAfterRemoval(login, index)
        publish = indexesAfterRemoval(publish, index)
        registration = indexesAfterRemoval(registration, index)
        off = indexesAfterRemoval(off, index)
      }
      const res = await saveProxiesLines(next, { allowEmpty: next.length === 0, login, publish, registration, off })
      if (res) notify.ok(PROXIES_TOAST.deletedMany(indexes.length))
      clearSelection()
      return true
    } catch (error) {
      notify.error(error, PROXIES_TOAST.notDeleted)
      return false
    }
  })

  /* Мёртвые — пачкой: по одной их удалять долго, а держать незачем. */
  const removeDead = async () => {
    if (rotateBusy.size) return
    const dead = rows.filter((r) => r.state === "dead").map((r) => r.index)
    if (await removeIndexes(dead, PROXY_CONFIRM.deleteDead(dead.length))) setFilter("all")
  }

  /* Действия над выбранными — те же, что у строки, только пачкой. Отметки
     считаются по всему списку, как и у одиночных: скрытые срезом строки
     своих отметок не теряют. */
  const setMarks = (patch: { off?: number[]; login?: number[]; publish?: number[]; registration?: number[] }, done?: string, failed: string = PROXIES_TOAST.notToggled) => mutateProxies(query.data?.proxies ?? [], async () => {
    try {
      await saveProxies(patch)
      if (done) notify.ok(done)
    } catch (error) {
      notify.error(error, failed)
    }
  })
  const union = (a: number[], b: number[]) => [...new Set([...a, ...b])]
  const minus = (a: number[], b: Set<number>) => a.filter((i) => !b.has(i))
  const mark = (field: "login" | "publish" | "registration", indexes: number[], checked: boolean) => {
    const current = field === "login" ? loginIndexes(rows) : field === "publish" ? publishIndexes(rows) : registrationIndexes(rows)
    const failed = field === "login" ? PROXIES_TOAST.notLogin : field === "publish" ? PROXIES_TOAST.notPublish : PROXIES_TOAST.notRegistration
    return setMarks({ [field]: checked ? union(current, indexes) : minus(current, new Set(indexes)) }, undefined, failed)
  }

  const actionsFor = (targets: ProxyRow[]) => {
    const indexes = targets.map((r) => r.index)
    const run: Record<ProxyActionKey, () => void> = {
      edit: () => setEditingIndex(indexes[0]),
      disable: () => void setMarks({ off: union(offIndexes(rows), indexes) }, PROXIES_TOAST.disabledMany(indexes.length)),
      enable: () => void setMarks({ off: minus(offIndexes(rows), new Set(indexes)) }, PROXIES_TOAST.enabledMany(indexes.length)),
      copy: () => void copyWithToast(targets.map((r) => r.proxy).join("\n"), PROXIES_TOAST.copied(targets.length)),
      "login-on": () => void mark("login", indexes, true),
      "login-off": () => void mark("login", indexes, false),
      "registration-on": () => void mark("registration", indexes, true),
      "registration-off": () => void mark("registration", indexes, false),
      "publish-on": () => void mark("publish", indexes, true),
      "publish-off": () => void mark("publish", indexes, false),
      noshadow: () => setNoshadow(targets.filter((r) => r.noshadow).map((r) => r.index)),
      renew: () => void renew(targets),
      rotate: () => void rotate(targets),
      remove: () => void removeIndexes(indexes, targets.length === 1 ? PROXY_CONFIRM.deleteOne(targets[0].proxy) : PROXY_CONFIRM.deleteMany(targets.length)),
    }
    return proxyActions(targets, (key) => run[key](), { elapsed, rotateBusy })
      .map((action) => ({ ...action, disabled: action.disabled || (mutating && action.key !== "copy") }))
  }
  const rowActions: ProxyRowActions = {
    locked: mutating,
    menu: actionsFor,
    toggleLogin: (index, checked) => void mark("login", [index], checked),
    toggleRegistration: (index, checked) => void mark("registration", [index], checked),
    togglePublish: (index, checked) => void mark("publish", [index], checked),
  }
  const bulk = actionsFor(chosen)

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
        sort={sort}
        dir={dir}
        onSort={onSort}
        rotateBusy={rotateBusy}
        actions={rowActions}
        marked={{ login: loginIndexes(rows).length, publish: publishIndexes(rows).length, registration: registrationIndexes(rows).length }}
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
                <Switch id="proxies-use" checked={query.data.enabled} disabled={mutating} onCheckedChange={toggleUse} />
                <Label htmlFor="proxies-use">{PROXIES_LABEL.use}</Label>
              </div>
              {filter === "dead" && counts.dead ? (
                <Button variant="destructive" disabled={mutating} onClick={() => void removeDead()}>
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
              <Button disabled={mutating} onClick={() => setAdding(true)}>
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
                registration={registrationIndexes(rows)}
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
          marks={{ login: loginIndexes(rows), publish: publishIndexes(rows), registration: registrationIndexes(rows), off: offIndexes(rows) }}
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
          registration={registrationIndexes(rows)}
          off={offIndexes(rows)}
          onClose={() => setEditingIndex(null)}
        />
      ) : null}
    </Page>
  )
}
