import { t, useLanguage } from "@/lib/i18n"
import { useRef, useState } from "react"
import { LockIcon, LockOpenIcon } from "lucide-react"

import type { UniqKey, UniqParam } from "@/api/types"
import { NumberInput, RangeInput, parseNumber } from "@/components/number-input"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"

import { UNIQ_LABELS } from "./labels"
import { applyPatch, isDecimal, numToField, parseClamped, sliderValues, snap, stepOf, type ParamPatch } from "./param-model"

/* Строка параметра: тумблер, подпись, вилка «от — до» с замком и ползунок
   под ними. Поля держат строку как набрали — в фокусе её не переписываем;
   число уходит наверх сразу, мусор не уходит и подсвечивается, а на уходе
   фокуса поле возвращается к сохранённому числу. */

interface ParamRowProps {
  paramKey: UniqKey
  param: UniqParam
  limits: [number, number]
  onPatch: (patch: ParamPatch) => void
}

export function ParamRow({ paramKey, param, limits, onPatch }: ParamRowProps) {
  useLanguage()
  const { label, icon: Icon } = UNIQ_LABELS[paramKey]
  const decimal = isDecimal(paramKey)
  const step = stepOf(paramKey)
  const disabled = !param.enabled

  const [draft, setDraft] = useState(() => ({
    min: numToField(param.min, decimal),
    max: numToField(param.max, decimal),
  }))

  const setField = (edge: "min" | "max", raw: string) => {
    setDraft((d) => ({ ...d, [edge]: raw }))
  }
  const showParam = (p: Pick<UniqParam, "min" | "max">) => {
    setDraft({ min: numToField(p.min, decimal), max: numToField(p.max, decimal) })
  }

  const change = (edge: "min" | "max", raw: string) => {
    setField(edge, raw)
    const n = parseClamped(raw, limits)
    if (n === null) return
    // вторая граница могла подтянуться — в поле показываем сразу
    const next = applyPatch(param, { [edge]: n })
    setField(edge === "min" ? "max" : "min", numToField(next[edge === "min" ? "max" : "min"], decimal))
    onPatch({ [edge]: n })
  }

  // RangeInput не открывает свои поля наружу: край узнаём по порядку — первое
  // «от», второе «до» (под замком поле одно, и оно же «от»)
  const fields = useRef<HTMLDivElement>(null)
  const edgeOf = (target: EventTarget | null): "min" | "max" | null => {
    const inputs = fields.current?.querySelectorAll("input")
    if (!inputs?.length) return null
    if (target === inputs[0]) return "min"
    return inputs.length > 1 && target === inputs[1] ? "max" : null
  }

  const invalid = parseNumber(draft.min) === null || parseNumber(draft.max) === null

  return (
    <div className="flex flex-col gap-3 border-b px-4 py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Switch checked={param.enabled} onCheckedChange={(v) => onPatch({ enabled: v })} aria-label={label} />
        <span className="flex min-w-0 items-center gap-2 text-sm font-medium whitespace-nowrap">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          {label}
        </span>
        <div
          ref={fields}
          className="ml-auto flex items-center gap-2"
          onBlur={(e) => {
            // фокус ушёл из пары полей — показываем сохранённые числа
            if (edgeOf(e.target) === null || edgeOf(e.relatedTarget) !== null) return
            showParam(param)
          }}
        >
          {/* замок — это одно значение вместо вилки: второе поле показывало бы
              то же число и только путало */}
          {param.locked ? (
            <NumberInput
              value={draft.min}
              onValueChange={(v) => change("min", v)}
              decimal={decimal}
              signed={limits[0] < 0}
              disabled={disabled}
              aria-invalid={parseNumber(draft.min) === null || undefined}
              aria-label={label}
              className="h-8 w-20 text-sm"
            />
          ) : (
            <RangeInput
              min={draft.min}
              max={draft.max}
              onMinChange={(v) => change("min", v)}
              onMaxChange={(v) => change("max", v)}
              decimal={decimal}
              signed={limits[0] < 0}
              invalid={invalid}
              disabled={disabled}
              label={label}
              inputClassName="w-20 h-8 text-sm"
            />
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            disabled={disabled}
            onClick={() => {
              const next = applyPatch(param, { locked: !param.locked })
              onPatch({ locked: next.locked })
              showParam(next)
            }}
            aria-label={param.locked ? t("Снять фиксацию") : t("Фиксировать значение")}
            className={cn(param.locked ? "text-foreground" : "text-muted-foreground")}
          >
            {param.locked ? <LockIcon /> : <LockOpenIcon />}
          </Button>
        </div>
      </div>
      <Slider
        value={sliderValues(param)}
        min={limits[0]}
        max={limits[1]}
        step={step}
        disabled={disabled}
        aria-label={label}
        onValueChange={(values) => {
          const list = typeof values === "number" ? [values] : [...values]
          const sorted = [...list].sort((a, b) => a - b)
          const next = {
            min: snap(sorted[0], step),
            max: snap(sorted[sorted.length - 1], step),
          }
          showParam(next)
          onPatch(next)
        }}
      />
    </div>
  )
}
