import { t, useLanguage } from "@/lib/i18n"
import { useEffect, useRef, useState } from "react"
import { CopyIcon } from "lucide-react"

import { saveSettings } from "@/api/misc"
import type { Settings } from "@/api/types"
import { IconButton } from "@/components/hint"
import { Switch } from "@/components/ui/switch"
import { copyWithToast } from "@/lib/native"
import { notify } from "@/lib/notify"

import { SETTINGS_LABEL, SETTINGS_TOAST } from "./labels"
import { createPhoneQr } from "./phone-qr"
import { SettingRow, SettingsGroup } from "./settings-row"

export function PhonePanel({
  phone,
  password,
}: Pick<Settings, "phone" | "password">) {
  useLanguage()
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{
    link: string
    image?: string
    error?: boolean
  } | null>(null)
  const guard = useRef(false)
  const link = phone.active ? phone.links[0] : undefined

  useEffect(() => {
    let active = true
    if (link) {
      void createPhoneQr(link)
        .then((image) => {
          if (active) setResult({ link, image })
        })
        .catch(() => {
          if (active) setResult({ link, error: true })
        })
    }
    return () => {
      active = false
    }
  }, [link])
  const qr = result?.link === link ? result?.image : undefined
  const qrError = result?.link === link && result?.error
  const port = link ? new URL(link).port : ""

  const toggle = async (on: boolean) => {
    if (guard.current) return
    guard.current = true
    setSaving(true)
    try {
      await saveSettings({ phone_access: on })
    } catch (error) {
      notify.error(error)
    } finally {
      guard.current = false
      setSaving(false)
    }
  }

  return (
    <SettingsGroup title={SETTINGS_LABEL.phoneTitle}>
      <SettingRow label={SETTINGS_LABEL.phone} htmlFor="settings-phone">
        <Switch
          id="settings-phone"
          checked={phone.active}
          disabled={saving || !password.set}
          onCheckedChange={(on) => void toggle(on)}
        />
        <p className="w-full text-xs text-muted-foreground">
          {password.set
            ? SETTINGS_LABEL.phoneHint
            : SETTINGS_LABEL.phoneNeedPassword}
        </p>
      </SettingRow>
      {phone.active ? (
        <div className="flex min-w-0 flex-col items-start gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-5">
          {qr ? (
            <img
              src={qr}
              alt={t("QR-код для подключения к Nimbus")}
              className="size-48 shrink-0 rounded-lg"
            />
          ) : null}
          <div className="flex min-w-0 flex-col gap-2">
            <p className="text-sm text-muted-foreground">
              {SETTINGS_LABEL.phoneScan}
            </p>
            <p className="text-xs text-muted-foreground" aria-live="polite">
              {port ? SETTINGS_LABEL.phonePortOpen(port) : null}{" "}
              {phone.connected ? SETTINGS_LABEL.phoneConnected : SETTINGS_LABEL.phoneWaiting}
            </p>
            {phone.links.map((address) => (
              <div key={address} className="flex min-w-0 items-center gap-1">
                <span className="min-w-0 font-mono text-sm break-all select-all">
                  {address}
                </span>
                <IconButton
                  label={SETTINGS_LABEL.copy}
                  icon={CopyIcon}
                  size="icon-sm"
                  onClick={() =>
                    void copyWithToast(address, SETTINGS_TOAST.copied)
                  }
                />
              </div>
            ))}
            {!phone.links.length ? (
              <p className="text-sm text-muted-foreground">
                {SETTINGS_LABEL.phoneUnavailable}
              </p>
            ) : null}
            {qrError ? (
              <p className="text-sm text-muted-foreground">
                {SETTINGS_LABEL.phoneQrError}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </SettingsGroup>
  )
}
