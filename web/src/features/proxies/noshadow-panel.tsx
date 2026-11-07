import { useLanguage } from "@/lib/i18n"
import { useMemo, useState } from "react"

import { Flag } from "@/components/flag"
import { NumberInput } from "@/components/number-input"
import { SimpleSelect } from "@/components/simple-select"
import { Button } from "@/components/ui/button"
import { Field, FieldGroup } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Switch } from "@/components/ui/switch"
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { notify } from "@/lib/notify"
import { cn } from "@/lib/utils"

import { NOSHADOW_LABEL as L, PROXIES_TOAST } from "./labels"
import {
  countryName,
  DEFAULT_MINUTES,
  generateNoshadow,
  MAX_MINUTES,
  NOSHADOW_COUNTRIES,
  noshadowAccounts,
  patchNoshadow,
  readNoshadow,
  readNoshadowAccount,
  writeNoshadow,
  type NoshadowPatch,
  type Transport,
} from "./noshadow"
import { saveProxiesLines } from "./proxies-store"

/* Прокси noshadow одной боковой панелью на два случая:

   - собрать: аккаунт (из строк, что уже в списке, или вставленной строки),
     страны, режим IP, порт и сколько строк на страну — строки дописываются
     к списку;
   - поправить выбранные: страна, режим и порт разом; что не трогали —
     остаётся как было.

   Строки человека сами не меняются: всё — по кнопке. Список уходит на сервер
   целиком, отметки строк сохраняются вместе с ним. */

type Keep<T> = T | "keep"

interface Marks {
  login: number[]
  publish: number[]
  off: number[]
}

const OTHER = "__other__"

export function NoshadowPanel({
  proxies,
  marks,
  editing,
  onClose,
}: {
  /** полный список строк (с учётками) */
  proxies: string[]
  marks: Marks
  /** номера строк для правки; не задан — панель собирает новые */
  editing?: number[]
  onClose: () => void
}) {
  useLanguage()
  const edit = editing != null
  const accounts = useMemo(() => noshadowAccounts(proxies), [proxies])

  const [account, setAccount] = useState(accounts[0]?.base ?? OTHER)
  const [pasted, setPasted] = useState("")
  const [countries, setCountries] = useState<string[]>(edit ? [] : ["US"])
  const [mode, setMode] = useState<Keep<"rotation" | "sticky">>(edit ? "keep" : "sticky")
  const [minutes, setMinutes] = useState(String(DEFAULT_MINUTES))
  const [transport, setTransport] = useState<Keep<Transport>>(edit ? "keep" : "http")
  const [perCountry, setPerCountry] = useState("1")
  const [renew, setRenew] = useState(false)
  const [saving, setSaving] = useState(false)

  const mins = Math.min(MAX_MINUTES, Math.max(1, Number(minutes) || DEFAULT_MINUTES))
  const per = Math.min(100, Math.max(1, Number(perCountry) || 1))
  const creds =
    account === OTHER
      ? readNoshadowAccount(pasted)
      : accounts.find((a) => a.base === account) ?? null

  const save = async (next: string[], done: string) => {
    // две одинаковые строки сервер свёл бы в одну, и отметки съехали бы;
    // сравниваем разобранный вид: пароль в списке закодирован, у новых — нет
    const key = (line: string) => {
      const n = readNoshadow(line)
      return n ? writeNoshadow(n) : line
    }
    if (new Set(next.map(key)).size !== next.length) {
      notify.warn(PROXIES_TOAST.wouldMerge)
      return
    }
    setSaving(true)
    try {
      const res = await saveProxiesLines(next, marks)
      if (res) notify.ok(done)
      onClose()
    } catch (error) {
      notify.error(error, edit ? PROXIES_TOAST.notChanged : PROXIES_TOAST.notAdded)
    } finally {
      setSaving(false)
    }
  }

  const submit = () => {
    if (edit) {
      const patch: NoshadowPatch = {}
      if (countries[0]) patch.country = countries[0]
      if (mode !== "keep") patch.minutes = mode === "sticky" ? mins : 0
      if (transport !== "keep") patch.transport = transport
      if (renew) patch.renew = true
      const chosen = new Set(editing)
      const next = proxies.map((line, i) => {
        const n = chosen.has(i) ? readNoshadow(line) : null
        return n ? writeNoshadow(patchNoshadow(n, patch)) : line
      })
      void save(next, PROXIES_TOAST.changed(editing.length))
      return
    }
    if (!creds) {
      notify.warn(PROXIES_TOAST.noAccount)
      return
    }
    const lines = generateNoshadow({
      ...creds,
      countries,
      perCountry: per,
      minutes: mode === "sticky" ? mins : 0,
      transport: transport === "keep" ? "http" : transport,
    })
    void save([...proxies, ...lines], PROXIES_TOAST.added(lines.length))
  }

  const ready = edit
    ? countries.length > 0 || mode !== "keep" || transport !== "keep" || renew
    : !!creds && countries.length > 0

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="gap-0">
        <SheetHeader>
          <SheetTitle>{edit ? L.editTitle(editing.length) : L.generateTitle}</SheetTitle>
        </SheetHeader>
        <FieldGroup className="min-h-0 flex-1 gap-4 overflow-y-auto px-4 pb-4 [&>*]:shrink-0">
          {edit ? null : (
            <Field>
              <Label>{L.account}</Label>
              {accounts.length ? (
                <SimpleSelect
                  value={account}
                  items={[...accounts.map((a) => ({ value: a.base, label: a.base })), { value: OTHER, label: L.otherAccount }]}
                  onValueChange={setAccount}
                  aria-label={L.account}
                />
              ) : null}
              {account === OTHER ? (
                <Input
                  value={pasted}
                  onChange={(e) => setPasted(e.target.value)}
                  placeholder={L.accountHint}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono"
                  aria-invalid={(pasted.trim() !== "" && !creds) || undefined}
                />
              ) : null}
            </Field>
          )}

          <div className="flex flex-wrap items-end gap-3">
            <Field className="w-auto">
              <Label>{L.mode}</Label>
              <ToggleGroup
                value={[mode]}
                onValueChange={(v) => v[0] && setMode(v[0] as Keep<"rotation" | "sticky">)}
                aria-label={L.mode}
              >
                {edit ? <ToggleGroupItem value="keep">{L.keep}</ToggleGroupItem> : null}
                <ToggleGroupItem value="rotation">{L.rotation}</ToggleGroupItem>
                <ToggleGroupItem value="sticky">{L.sticky}</ToggleGroupItem>
              </ToggleGroup>
            </Field>
            {mode === "sticky" ? (
              <Field className="w-20">
                <Label htmlFor="ns-minutes">{L.minutes}</Label>
                <NumberInput id="ns-minutes" value={minutes} onValueChange={setMinutes} />
              </Field>
            ) : null}
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <Field className="w-auto">
              <Label>{L.transport}</Label>
              <ToggleGroup
                value={[transport]}
                onValueChange={(v) => v[0] && setTransport(v[0] as Keep<Transport>)}
                aria-label={L.transport}
              >
                {edit ? <ToggleGroupItem value="keep">{L.keep}</ToggleGroupItem> : null}
                <ToggleGroupItem value="http">{L.http}</ToggleGroupItem>
                <ToggleGroupItem value="socks">{L.socks}</ToggleGroupItem>
              </ToggleGroup>
            </Field>
            {edit ? null : (
              <Field className="w-20">
                <Label htmlFor="ns-per">{L.perCountry}</Label>
                <NumberInput id="ns-per" value={perCountry} onValueChange={setPerCountry} />
              </Field>
            )}
          </div>

          {edit ? (
            <div className="flex items-center gap-2">
              <Switch id="ns-renew" checked={renew} onCheckedChange={setRenew} />
              <Label htmlFor="ns-renew">{L.renew}</Label>
            </div>
          ) : null}

          <CountryPicker multiple={!edit} value={countries} onChange={setCountries} />
        </FieldGroup>
        <SheetFooter className="shrink-0 flex-row flex-wrap items-center justify-end gap-2 border-t">
          {edit ? null : (
            <span className="mr-auto basis-full text-xs text-muted-foreground sm:basis-auto">
              {L.total(countries.length * per)}
            </span>
          )}
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {L.cancel}
          </Button>
          <Button onClick={submit} disabled={saving || !ready}>
            {edit ? L.apply : L.generate}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

/* Список стран с поиском по названию и коду. multiple — флажками (собрать на
   несколько стран), иначе одна страна или ничего («не менять»). */
function CountryPicker({
  multiple,
  value,
  onChange,
}: {
  multiple: boolean
  value: string[]
  onChange: (value: string[]) => void
}) {
  const language = useLanguage()
  const [search, setSearch] = useState("")
  // выбранные при открытии — сверху; порядок дальше не меняется, чтобы
  // список не прыгал под курсором при каждом клике
  const [pinned] = useState(() => new Set(value))
  const all = useMemo(
    () =>
      NOSHADOW_COUNTRIES.map((code) => ({ code, name: countryName(code) })).sort(
        (a, b) => Number(pinned.has(b.code)) - Number(pinned.has(a.code)) || a.name.localeCompare(b.name, language)
      ),
    [pinned, language]
  )
  const q = search.trim().toLowerCase()
  const shown = q ? all.filter((c) => c.name.toLowerCase().includes(q) || c.code.toLowerCase() === q) : all
  const picked = new Set(value)
  const toggle = (code: string) => {
    if (!multiple) onChange(picked.has(code) ? [] : [code])
    else onChange(picked.has(code) ? value.filter((c) => c !== code) : [...value, code])
  }

  return (
    <Field className="min-h-0 flex-1">
      <div className="flex items-center justify-between gap-2">
        <Label>{multiple ? L.countries : L.country}</Label>
        <span className="text-xs text-muted-foreground">
          {value.length ? value.join(", ") : multiple ? "" : L.keep}
        </span>
      </div>
      <Input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={L.countrySearch}
        aria-label={L.countrySearch}
        className="shrink-0"
        autoComplete="off"
        spellCheck={false}
      />
      <ScrollArea className="min-h-40 flex-1 rounded-md border">
        <ul className="p-1" role="listbox" aria-multiselectable={multiple || undefined}>
          {shown.map((c) => (
            <li key={c.code}>
              <button
                type="button"
                role="option"
                aria-selected={picked.has(c.code)}
                onClick={() => toggle(c.code)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted pointer-coarse:min-h-10",
                  picked.has(c.code) && "bg-primary/10 text-foreground"
                )}
              >
                <Flag code={c.code} />
                <span className="min-w-0 flex-1 truncate">{c.name}</span>
                <span className="text-xs text-muted-foreground tabular-nums">{c.code}</span>
              </button>
            </li>
          ))}
        </ul>
      </ScrollArea>
    </Field>
  )
}
