import { useState, type ComponentProps } from "react"
import { CopyIcon } from "lucide-react"

import { saveSettings } from "@/api/misc"
import type { Settings } from "@/api/types"
import { IconButton } from "@/components/hint"
import { NumberInput } from "@/components/number-input"
import { SimpleSelect } from "@/components/simple-select"
import { Input } from "@/components/ui/input"
import { useLanguage } from "@/lib/i18n"
import { copyWithToast } from "@/lib/native"
import { notify } from "@/lib/notify"

import { ACCESS_TEXT } from "./access-labels"
import { externalConnection } from "./connection-link"
import { SETTINGS_LABEL, SETTINGS_TOAST } from "./labels"
import { PasswordPanel } from "./password-panel"
import { PhonePanel } from "./phone-panel"
import { SettingRow, SettingsGroup } from "./settings-row"

const localHost = (host: string) =>
  ["127.0.0.1", "localhost", "::1"].includes(host)

export function AccessPanel({
  settings,
  portInput,
}: {
  settings: Settings
  portInput: ComponentProps<typeof NumberInput>
}) {
  const text = ACCESS_TEXT[useLanguage()]
  const [savingHost, setSavingHost] = useState(false)
  const savedHost = settings.bind_explicit === true ? settings.host : "127.0.0.1"
  const items: ComponentProps<typeof SimpleSelect>["items"][number][] = [
    { value: "127.0.0.1", label: text.local },
    {
      value: "0.0.0.0",
      label: text.all,
      disabled: !settings.password.set,
      reason: !settings.password.set ? text.needPassword : undefined,
    },
  ]
  if (!items.some((item) => item.value === savedHost))
    items.push({ value: savedHost, label: savedHost })

  const setHost = async (host: string) => {
    if (
      savingHost ||
      (host === savedHost && settings.bind_explicit === true) ||
      (!localHost(host) && !settings.password.set)
    )
      return
    setSavingHost(true)
    try {
      await saveSettings({ host })
    } catch (error) {
      notify.error(error)
    } finally {
      setSavingHost(false)
    }
  }
  const networkActive =
    settings.phone.on ||
    settings.phone.active ||
    !localHost(settings.bound.host) ||
    !localHost(savedHost)

  return (
    <SettingsGroup title={text.title}>
      {settings.password.available ? (
        <PasswordPanel
          password={settings.password}
          networkActive={networkActive}
        />
      ) : null}
      <SettingRow label={text.bind}>
        <SimpleSelect
          aria-label={text.bind}
          value={savedHost}
          items={items}
          disabled={savingHost}
          onValueChange={(host) => void setHost(host)}
        />
        <p className="w-full text-xs text-muted-foreground">{text.bindHint}</p>
      </SettingRow>
      <SettingRow label={SETTINGS_LABEL.port} htmlFor="settings-port">
        <NumberInput {...portInput} id="settings-port" className="w-28" />
        <p className="w-full text-xs text-muted-foreground tabular">
          {text.active}: {settings.bound.host}:{settings.bound.port}
        </p>
        {savedHost !== settings.bound.host ||
        settings.port !== settings.bound.port ? (
          <p className="w-full text-xs text-muted-foreground tabular">
            {text.pending}: {savedHost}:{settings.port}
          </p>
        ) : null}
      </SettingRow>
      <PhonePanel phone={settings.phone} password={settings.password} />
      <p className="px-4 py-3 text-xs text-muted-foreground">{text.secureAccess}</p>
      <ExternalAddress port={settings.bound.port} />
    </SettingsGroup>
  )
}

function ExternalAddress({ port }: { port: number }) {
  const text = ACCESS_TEXT[useLanguage()]
  const [address, setAddress] = useState("")
  // Manual entry only: no external lookup, settings write or reachability claim.
  const connection = externalConnection(address, port)
  return (
    <SettingRow label={text.external} htmlFor="settings-external-address">
      <Input
        id="settings-external-address"
        value={address}
        placeholder={text.externalPlaceholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => setAddress(event.target.value)}
      />
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 font-mono text-xs break-all select-all">
          {connection?.link}
        </span>
        <IconButton
          label={text.copyAddress}
          icon={CopyIcon}
          size="icon-sm"
          disabled={!connection}
          onClick={() =>
            connection &&
            void copyWithToast(connection.address, SETTINGS_TOAST.copied)
          }
        />
        <IconButton
          label={text.copyLink}
          icon={CopyIcon}
          size="icon-sm"
          disabled={!connection}
          onClick={() =>
            connection &&
            void copyWithToast(connection.link, SETTINGS_TOAST.copied)
          }
        />
      </div>
      <p className="w-full text-xs text-muted-foreground">{text.externalHint}</p>
      {address.trim() && !connection ? (
        <p className="w-full text-xs text-destructive" role="alert">
          {text.addressInvalid}
        </p>
      ) : null}
    </SettingRow>
  )
}
