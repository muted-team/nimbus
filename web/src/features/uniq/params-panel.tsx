import { t, useLanguage } from "@/lib/i18n"
import { UNIQ_KEYS, type UniqKey, type UniqParam } from "@/api/types"
import { Panel } from "@/components/panel"
import { cn } from "@/lib/utils"

import type { ParamPatch } from "./param-model"
import { ParamRow } from "./param-row"

/* Параметры уникализации: по строке на ключ из таблицы. При выключенном
   мастере настройки видны, но не редактируются. */

interface ParamsPanelProps {
  master: boolean
  params: Record<UniqKey, UniqParam>
  limits: Record<UniqKey, [number, number]>
  onPatch: (key: UniqKey, patch: ParamPatch) => void
}

export function ParamsPanel({ master, params, limits, onPatch }: ParamsPanelProps) {
  useLanguage()
  return (
    <Panel
      title={t("Параметры")}
      flush
      className={cn(!master && "pointer-events-none opacity-60")}
      inert={!master || undefined}
    >
      {UNIQ_KEYS.map((key) => (
        <ParamRow
          key={key}
          paramKey={key}
          param={params[key]}
          limits={limits[key]}
          onPatch={(patch) => onPatch(key, patch)}
        />
      ))}
    </Panel>
  )
}
