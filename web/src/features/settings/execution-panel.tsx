import { useExecutionCapabilities, useExecutionStates } from "@/api/execution"
import type { ExecutionModes, ExecutorMode, Operation } from "@/api/execution"
import { saveSettings } from "@/api/misc"
import type { Settings } from "@/api/types"
import { notify } from "@/lib/notify"
import { SettingRow, SettingsGroup } from "./settings-row"

const OPERATIONS: Operation[] = ["login", "publish", "logout"]
const LABELS = { login: "Вход", publish: "Публикация", logout: "Выход" }
const MODE_LABELS = { 1: "Low", 2: "Medium", 3: "High", 4: "Max" }

export function ExecutionPanel({ settings }: { settings: Settings }) {
  const caps = useExecutionCapabilities()
  const states = useExecutionStates()
  const modes: ExecutionModes = settings.execution_modes ?? { login: 0, publish: 0, logout: 0 }
  const update = async (operation: Operation, mode: ExecutorMode) => {
    try { await saveSettings({ execution_modes: { ...modes, [operation]: mode } }) }
    catch (error) { notify.error(error) }
  }
  const saved = Object.entries(states.data ?? {}).flatMap(([name, rows]) =>
    (["3", "4"] as const).filter((mode) => rows[mode].saved).map((mode) => `${name} (режим ${mode})`))
  return <SettingsGroup title="Исполнение операций">
    {OPERATIONS.map((operation) => <SettingRow key={operation} label={LABELS[operation]}>
      <select aria-label={`Исполнитель: ${LABELS[operation]}`} className="h-9 max-w-full rounded-md border bg-background px-2 text-sm"
        value={modes[operation]} onChange={(event) => void update(operation, Number(event.target.value) as ExecutorMode)}>
        <option value={0}>Текущий HTTP</option>
        {([1, 2, 3, 4] as const).map((mode) => {
          const row = caps.data?.operations[operation].find((row) => row.mode === mode)
          return <option key={mode} value={mode} disabled={!row?.available}>{MODE_LABELS[mode]}{row?.available ? "" : " — недоступен"}</option>
        })}
      </select>
      <div className="w-full text-xs text-muted-foreground">
        {caps.isPending ? "Проверяем доступность исполнителей…" : caps.isError ? "Не удалось проверить возможности сервера" :
          caps.data?.operations[operation].filter((row) => row.mode >= 3).map((row) =>
            <p key={row.mode}>{MODE_LABELS[row.mode]}: {row.available ? (row.live_proven ? "доступен" : "доступен; живая проверка не подтверждена") : row.reason}</p>)}
      </div>
    </SettingRow>)}
    <SettingRow label="Видимость браузерной публикации">
      <select aria-label="Видимость браузерной публикации" className="h-9 max-w-full rounded-md border bg-background px-2 text-sm"
        value={settings.browser_visibility ?? "public"} onChange={async (event) => {
          try { await saveSettings({ browser_visibility: event.target.value as "public" | "private" }) }
          catch (error) { notify.error(error) }
        }}>
        <option value="public">Публичная</option><option value="private">Приватная</option>
      </select>
      <p className="w-full text-xs text-muted-foreground">Браузерный исполнитель сейчас поддерживает только явно выбранную приватную публикацию.</p>
    </SettingRow>
    {saved.length > 0 ? <p className="border-t px-4 py-3 text-xs text-muted-foreground break-words">Сохранённые браузерные состояния: {saved.join(", ")}. Наличие состояния не подтверждает действующий вход.</p> : null}
  </SettingsGroup>
}
