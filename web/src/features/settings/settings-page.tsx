import { useLanguage } from "@/lib/i18n"
import { useEffect, useRef } from "react"

import { saveSettings, useSettings } from "@/api/misc"
import type { BrowserProfile, ProxyOnDeath, Settings, SettingsPatch } from "@/api/types"
import { sectionTitle } from "@/app/sections"
import { NumberInput, parseNumber } from "@/components/number-input"
import { Page, PageBody, PageHeader } from "@/components/page"
import { QueryView } from "@/components/state-view"
import { SimpleSelect } from "@/components/simple-select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useAutosave } from "@/hooks/use-autosave"
import { useSyncedInput } from "@/hooks/use-synced-input"
import { notify } from "@/lib/notify"

import { BROWSER_LABEL, ON_DEATH_LABEL, SETTINGS_LABEL } from "./labels"
import { LanguagePanel } from "./language-panel"
import { PasswordPanel } from "./password-panel"
import { PhonePanel } from "./phone-panel"
import { ServerPanel } from "./server-panel"
import { ThemePanel } from "./theme-panel"
import { SettingRow, SettingsGroup } from "./settings-row"

/* Пределы порта — как у сервера (main.py): иначе набранные 80 молча
   превращались в 1024, и человек не понимал, почему адрес не тот. */
const PORT_MIN = 1
const PORT_MAX = 65535

const clamp = (n: number, min: number, max: number) => Math.min(Math.max(n, min), max)

export default function SettingsPage() {
  useLanguage()
  useLanguage()
  const query = useSettings()

  return (
    <Page>
      <PageHeader title={sectionTitle("settings")} />
      <PageBody width="narrow">
        <QueryView query={query}>{(settings) => <SettingsForm settings={settings} />}</QueryView>
      </PageBody>
    </Page>
  )
}

interface Draft {
  threads: string
  serverWait: string
  port: string
}

function SettingsForm({ settings }: { settings: Settings }) {
  useLanguage()
  // правка уходит на сервер до того, как поле вернётся к серверному значению
  const commitRef = useRef<() => void>(() => {})
  const commit = () => commitRef.current()

  const threads = useSyncedInput(String(settings.threads), commit)
  const serverWait = useSyncedInput(String(settings.server_wait_min), commit)
  const port = useSyncedInput(String(settings.port), commit)
  const draft: Draft = {
    threads: threads.value,
    serverWait: serverWait.value,
    port: port.value,
  }

  // уходит только то, что отличается от записанного; мусор не шлём
  const { flush } = useAutosave(
    draft,
    async (d) => {
      const patch: SettingsPatch = {}
      const threadsN = parseNumber(d.threads, settings.threads)
      if (threadsN != null && threadsN !== settings.threads)
        patch.threads = clamp(Math.round(threadsN), 1, settings.threads_max)
      const waitN = parseNumber(d.serverWait, settings.server_wait_min)
      if (waitN != null && waitN !== settings.server_wait_min)
        patch.server_wait_min = clamp(Math.round(waitN), 1, settings.server_wait_max)
      const portN = parseNumber(d.port, settings.port)
      if (portN != null && portN !== settings.port)
        patch.port = clamp(Math.round(portN), PORT_MIN, PORT_MAX)
      if (Object.keys(patch).length) await saveSettings(patch)
    },
    { delay: 600, onError: (error) => notify.error(error) }
  )

  useEffect(() => {
    commitRef.current = () => void flush()
  }, [flush])

  const setOnDeath = async (value: ProxyOnDeath) => {
    try {
      await saveSettings({ proxy_on_death: value })
    } catch (error) {
      notify.error(error)
    }
  }

  const setBrowser = async (browser_profile: BrowserProfile) => {
    try { await saveSettings({ browser_profile }) }
    catch (error) { notify.error(error) }
  }

  return (
    <>
      <ThemePanel />
      <LanguagePanel />
      <SettingsGroup title={SETTINGS_LABEL.browserGroup}>
        <SettingRow label={SETTINGS_LABEL.browser}>
          <SimpleSelect
            aria-label={SETTINGS_LABEL.browser}
            value={settings.browser_profile ?? "firefox155"}
            items={(settings.browser_profiles ?? ["chrome152", "firefox155"]).map((value) => ({ value, label: BROWSER_LABEL[value] }))}
            onValueChange={(value) => void setBrowser(value)}
          />
          {settings.browser_profile && settings.browser_profile !== settings.browser_profile_active ?
            <p className="w-full text-xs text-muted-foreground">{SETTINGS_LABEL.browserPending}</p> : null}
        </SettingRow>
      </SettingsGroup>
      <SettingsGroup title={SETTINGS_LABEL.publishing}>
        <SettingRow label={SETTINGS_LABEL.threads} htmlFor="settings-threads">
          <NumberInput
            id="settings-threads"
            className="w-28"
            value={threads.value}
            onValueChange={threads.onChange}
            onFocus={threads.onFocus}
            onBlur={threads.onBlur}
          />
        </SettingRow>
        <SettingRow label={SETTINGS_LABEL.proxyOnDeath}>
          <ToggleGroup
            value={[settings.proxy_on_death]}
            onValueChange={(group) => {
              const next = group[0] as ProxyOnDeath | undefined
              if (next && next !== settings.proxy_on_death) void setOnDeath(next)
            }}
            aria-label={SETTINGS_LABEL.proxyOnDeath}
          >
            {(["swap", "stop"] as const).map((value) => (
              <ToggleGroupItem key={value} value={value}>
                {ON_DEATH_LABEL[value]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </SettingRow>
        <SettingRow label={SETTINGS_LABEL.serverWait} htmlFor="settings-server-wait">
          <NumberInput
            id="settings-server-wait"
            className="w-28"
            value={serverWait.value}
            onValueChange={serverWait.onChange}
            onFocus={serverWait.onFocus}
            onBlur={serverWait.onBlur}
          />
        </SettingRow>
      </SettingsGroup>
      <SettingsGroup
        title={SETTINGS_LABEL.address}
        meta={
          <span className="ml-auto text-xs font-normal text-muted-foreground tabular">
            {SETTINGS_LABEL.now} {settings.bound.host}:{settings.bound.port}
          </span>
        }
      >
        <SettingRow label={SETTINGS_LABEL.port} htmlFor="settings-port">
          <NumberInput
            id="settings-port"
            className="w-28"
            value={port.value}
            onValueChange={port.onChange}
            onFocus={port.onFocus}
            onBlur={port.onBlur}
          />
        </SettingRow>
      </SettingsGroup>
      <ServerPanel server={settings.server} />
      {settings.password.available ? <PasswordPanel password={settings.password} /> : null}
      <PhonePanel phone={settings.phone} password={settings.password} />
    </>
  )
}
