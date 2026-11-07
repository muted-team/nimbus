import { useLanguage } from "@/lib/i18n"
import { useState } from "react"
import { CircleCheckIcon, CircleXIcon } from "lucide-react"

import { errorText } from "@/api/client"
import { recheckServer, saveSettings, useServerCheck } from "@/api/misc"
import type { Settings } from "@/api/types"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { useAutosave } from "@/hooks/use-autosave"

import { SERVER_LABEL } from "./labels"
import { SettingRow, SettingsGroup } from "./settings-row"

type Status =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "ok"; ms: number }
  | { state: "fail"; error: string }

/* Адрес нашего сервера и его доступность. Адрес сохраняется сам — после
   паузы в наборе или по Enter; следом идёт проверка соединения. Любая правка
   поля сбрасывает статус: он относится к записанному адресу, а не к тому,
   что набирается сейчас. Пустое поле — сервер по умолчанию. */
export function ServerPanel({ server }: { server: Settings["server"] }) {
  useLanguage()
  const [value, setValue] = useState(server.url)
  // поле правят — статус записанного адреса к набранному не относится
  const [dirty, setDirty] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const check = useServerCheck()

  const { saving, flush } = useAutosave(
    value,
    async (v) => {
      const next = v.trim()
      // то же, что записано, или пустое при встроенном — слать нечего
      if (next === server.url || (!next && !server.custom)) {
        setDirty(false)
        return
      }
      await saveSettings({ server: next })
      setDirty(false)
      await recheckServer()
    },
    {
      delay: 800,
      onError: (error) => {
        setDirty(false)
        setSaveError(errorText(error))
      },
    }
  )

  const change = (next: string) => {
    setValue(next)
    setDirty(true)
    setSaveError(null)
  }

  const status: Status = dirty
    ? { state: "idle" }
    : saving || check.isFetching
      ? { state: "checking" }
      : saveError
        ? { state: "fail", error: saveError }
        : check.isError
          ? { state: "fail", error: errorText(check.error) }
          : check.data?.ok
            ? { state: "ok", ms: check.data.ms }
            : check.data
              ? { state: "fail", error: errorText(check.data.error) }
              : { state: "idle" }

  return (
    <SettingsGroup title={SERVER_LABEL.title}>
      <SettingRow label={SERVER_LABEL.address} htmlFor="settings-server">
        <Input
          id="settings-server"
          value={value}
          placeholder={server.default}
          onChange={(e) => change(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void flush()
          }}
          autoComplete="off"
          spellCheck={false}
        />
        <ServerStatus status={status} />
      </SettingRow>
    </SettingsGroup>
  )
}

function ServerStatus({ status }: { status: Status }) {
  useLanguage()
  // высота строки держится и без статуса — панель не прыгает при наборе
  return (
    <div className="flex min-h-5 w-full items-center gap-2 text-xs">
      {status.state === "checking" ? (
        <>
          <Spinner className="size-3.5" />
          <span className="text-muted-foreground">{SERVER_LABEL.checking}</span>
        </>
      ) : status.state === "ok" ? (
        <>
          <CircleCheckIcon className="size-3.5 text-success" />
          <span>{SERVER_LABEL.ok}</span>
          <span className="text-muted-foreground tabular">
            · {status.ms} {SERVER_LABEL.ms}
          </span>
        </>
      ) : status.state === "fail" ? (
        <>
          <CircleXIcon className="size-3.5 text-destructive" />
          <span className="text-destructive">
            {SERVER_LABEL.fail}: {status.error}
          </span>
        </>
      ) : null}
    </div>
  )
}
