import { useEffect, useState } from "react"
import {
  ArrowDownToLineIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
} from "lucide-react"

import { useChangelog } from "@/api/misc"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { SettingRow, SettingsGroup } from "@/features/settings/settings-row"
import { useLanguage } from "@/lib/i18n"
import { openExternal } from "@/lib/native"

const RELEASES = "https://github.com/muted-team/nimbus/releases"
export interface UpdateStatus {
  current_version: string
  latest_version?: string
  available: boolean
  supported: boolean
  reason?: string
  release_url: string
  notes?: string
  state: "idle" | "ready"
  error?: string
  can_restart?: boolean
}
interface UpdateBridge {
  check_client_update: () => Promise<UpdateStatus>
  prepare_client_update: () => Promise<UpdateStatus>
  restart_client_update?: () => Promise<{ error?: string }>
  open_client_update?: () => Promise<{ error?: string }>
}
function nativeBridge(): UpdateBridge | undefined {
  const bridge = window.pywebview?.api as unknown as
    Partial<UpdateBridge> | undefined
  return bridge?.check_client_update && bridge.prepare_client_update
    ? (bridge as UpdateBridge)
    : undefined
}
const labels = {
  ru: {
    title: "Обновления Nimbus",
    version: "Обновление клиента",
    check: "Проверить обновления",
    checking: "Проверяем GitHub…",
    prepare: "Скачать обновление",
    downloading: "Загружаем и проверяем…",
    restart: "Перезапустить и обновить",
    restarting: "Перезапускаем…",
    ready:
      "Обновление проверено и готово. Сохраните правки перед перезапуском; ваши данные останутся на месте.",
    manual: "Открыть GitHub Releases",
    browser:
      "Обновление устанавливается в настольном приложении. Для этой установки скачайте подходящий пакет из GitHub Releases.",
    folder: "Открыть папку обновления",
    manualReady:
      "Пакет проверен. Автоматическое применение для этой установки недоступно. Полностью закройте Nimbus перед ручным обновлением; сохраните папку с вашими данными.",
    newer: "Доступна версия",
    current: "Установлена последняя версия",
    safe: "Пакет проверяется по SHA-256 GitHub. Данные и текущая версия сохраняются.",
    notes: "Что нового",
    failed: "Не удалось выполнить обновление. Попробуйте позже.",
    idle: "Проверка опубликованных стабильных релизов GitHub",
  },
  en: {
    title: "Nimbus updates",
    version: "Client update",
    check: "Check for updates",
    checking: "Checking GitHub…",
    prepare: "Download update",
    downloading: "Downloading and verifying…",
    restart: "Restart and update",
    restarting: "Restarting…",
    ready:
      "The verified update is ready. Save your edits before restarting; your data will stay in place.",
    manual: "Open GitHub Releases",
    browser:
      "Updates are installed in the desktop app. Download the matching package from GitHub Releases for this installation.",
    folder: "Open update folder",
    manualReady:
      "The package is verified. Automatic installation is unavailable for this installation. Fully close Nimbus before updating manually; keep your data folder.",
    newer: "Available version",
    current: "You have the latest version",
    safe: "The package is verified against GitHub SHA-256. Your data and current version are preserved.",
    notes: "What's new",
    failed: "The update could not be completed. Please try again later.",
    idle: "Check published stable GitHub releases",
  },
  uk: {
    title: "Оновлення Nimbus",
    version: "Оновлення клієнта",
    check: "Перевірити оновлення",
    checking: "Перевіряємо GitHub…",
    prepare: "Завантажити оновлення",
    downloading: "Завантажуємо та перевіряємо…",
    restart: "Перезапустити й оновити",
    restarting: "Перезапускаємо…",
    ready:
      "Оновлення перевірено й готове. Збережіть зміни перед перезапуском; ваші дані залишаться на місці.",
    manual: "Відкрити GitHub Releases",
    browser:
      "Оновлення встановлюється в настільному застосунку. Для цієї установки завантажте відповідний пакет з GitHub Releases.",
    folder: "Відкрити папку оновлення",
    manualReady:
      "Пакет перевірено. Автоматичне встановлення для цієї установки недоступне. Повністю закрийте Nimbus перед ручним оновленням; збережіть папку з вашими даними.",
    newer: "Доступна версія",
    current: "Встановлена остання версія",
    safe: "Пакет перевіряється за SHA-256 GitHub. Дані та поточна версія зберігаються.",
    notes: "Що нового",
    failed: "Не вдалося виконати оновлення. Спробуйте пізніше.",
    idle: "Перевірка опублікованих стабільних релізів GitHub",
  },
}

export function ClientUpdates() {
  const lang = useLanguage()
  const text = labels[lang]
  const changelog = useChangelog()
  const [native, setNative] = useState(
    () => typeof window !== "undefined" && Boolean(nativeBridge())
  )
  const [status, setStatus] = useState<UpdateStatus>()
  const [busy, setBusy] = useState<"check" | "prepare" | "restart" | null>(null)
  const [error, setError] = useState<string>()
  useEffect(() => {
    const ready = () => setNative(Boolean(nativeBridge()))
    window.addEventListener("pywebviewready", ready)
    ready()
    return () => window.removeEventListener("pywebviewready", ready)
  }, [])

  async function run(action: "check" | "prepare" | "restart") {
    const bridge = nativeBridge()
    if (!bridge || busy) return
    setBusy(action)
    setError(undefined)
    try {
      if (action === "restart") {
        if (!status?.can_restart || !bridge.restart_client_update) return
        const result = await bridge.restart_client_update()
        if (result.error) throw new Error(result.error)
        return
      }
      const result = await (action === "check"
        ? bridge.check_client_update()
        : bridge.prepare_client_update())
      if (result.error) throw new Error(result.error)
      setStatus(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : text.failed)
    } finally {
      setBusy(null)
    }
  }
  const canRestart = Boolean(
    status?.can_restart && nativeBridge()?.restart_client_update
  )
  const version = status?.current_version || changelog.data?.version
  const message =
    busy === "check"
      ? text.checking
      : busy === "prepare"
        ? text.downloading
        : busy === "restart"
          ? text.restarting
          : status?.state === "ready"
            ? canRestart
              ? text.ready
              : text.manualReady
            : status
              ? status.available
                ? `${text.newer} ${status.latest_version}`
                : text.current
              : text.idle

  return (
    <SettingsGroup
      title={text.title}
      meta={
        version ? (
          <span className="text-xs tabular">v{version}</span>
        ) : undefined
      }
    >
      <SettingRow label={text.version}>
        <div className="flex w-full flex-col items-start gap-3">
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : (
            <div
              className="flex items-center gap-2 text-sm"
              role="status"
              aria-live="polite"
            >
              {busy ? (
                <Spinner />
              ) : status?.state === "ready" ? (
                <ShieldCheckIcon className="size-4 shrink-0 text-success" />
              ) : null}
              <span>{message}</span>
            </div>
          )}
          {!native || (status && !status.supported) ? (
            <p className="text-sm text-muted-foreground">{text.browser}</p>
          ) : null}
          {native ? (
            <div className="flex flex-wrap gap-2">
              <Button
                data-action="check"
                variant="outline"
                disabled={Boolean(busy) || status?.state === "ready"}
                onClick={() => void run("check")}
              >
                <RefreshCwIcon />
                {text.check}
              </Button>
              {status?.available &&
              status.supported &&
              status.state !== "ready" ? (
                <Button
                  data-action="prepare"
                  disabled={Boolean(busy)}
                  onClick={() => void run("prepare")}
                >
                  <ArrowDownToLineIcon />
                  {text.prepare}
                </Button>
              ) : null}
            </div>
          ) : null}
          {status?.state === "ready" &&
          !canRestart &&
          nativeBridge()?.open_client_update ? (
            <Button
              variant="outline"
              onClick={() => {
                void nativeBridge()
                  ?.open_client_update?.()
                  .then((result) => {
                    if (result.error) setError(result.error)
                  })
                  .catch(() => setError(text.failed))
              }}
            >
              {text.folder}
            </Button>
          ) : null}
          {status?.state === "ready" && canRestart ? (
            <Button
              data-action="restart"
              disabled={Boolean(busy)}
              onClick={() => void run("restart")}
            >
              <RefreshCwIcon />
              {text.restart}
            </Button>
          ) : null}
          {status?.supported ? (
            <p className="text-xs text-muted-foreground">{text.safe}</p>
          ) : null}
          <Button
            variant="link"
            className="h-auto px-0"
            onClick={() => openExternal(RELEASES)}
          >
            <ExternalLinkIcon />
            {text.manual}
          </Button>
          {status?.notes ? (
            <details className="w-full text-sm">
              <summary className="cursor-pointer text-muted-foreground">
                {text.notes}
              </summary>
              <p className="mt-2 break-words whitespace-pre-wrap">
                {status.notes}
              </p>
            </details>
          ) : null}
        </div>
      </SettingRow>
    </SettingsGroup>
  )
}
