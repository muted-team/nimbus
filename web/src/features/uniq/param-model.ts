import { UNIQ_KEYS, type UniqKey, type UniqParam, type UniqSettings } from "@/api/types"
import { parseNumber } from "@/components/number-input"

/* Вилки и замок параметров уникализатора — чистая логика без React: разбор
   строк полей, зажим в пределы сервера, поведение границ и подпись того, от
   чего зависит превью. */

/** Шаг параметра: у гаммы дробный, у остальных целый. */
export const stepOf = (key: UniqKey) => (key === "gamma" ? 0.01 : 1)

/** Единственный дробный параметр — гамма. */
export const isDecimal = (key: UniqKey) => key === "gamma"

/** Число для поля: без разрядов, дробная часть — запятой. */
export function numToField(n: number, decimal: boolean): string {
  return decimal ? String(n).replace(".", ",") : String(n)
}

/** Строка поля -> число, зажатое в пределы сервера; пусто и мусор -> null. */
export function parseClamped(raw: string, limits: [number, number]): number | null {
  const n = parseNumber(raw)
  return n === null ? null : Math.min(Math.max(n, limits[0]), limits[1])
}

/** Значение к шагу ползунка: гасит шум плавающей точки (0.30000000000004 -> 0.3). */
export function snap(n: number, step: number): number {
  return step >= 1 ? Math.round(n) : Number((Math.round(n / step) * step).toFixed(2))
}

export type ParamPatch = Partial<UniqParam>

/**
 * Одна правка параметра. Границы не пересекаются: двинутая тянет вторую за
 * собой. Замок — одно значение вместо вилки: включение приравнивает «до» к
 * «от», правка «от» тянет «до»; выключение меняет только доступность поля.
 */
export function applyPatch(p: UniqParam, patch: ParamPatch): UniqParam {
  const next: UniqParam = { ...p, ...patch }
  if (next.locked && (patch.locked || patch.min !== undefined)) {
    next.max = next.min
  } else if (next.min > next.max) {
    if (patch.min !== undefined) next.max = next.min
    else next.min = next.max
  }
  return next
}

/** Значения ползунка: при замке один бегунок, при вилке два. */
export function sliderValues(p: UniqParam): number[] {
  return p.locked ? [p.min] : [p.min, p.max]
}

/**
 * Числовая часть настроек без мастера и пределов. Замок — одно значение:
 * если сервер прислал замок с разошедшейся вилкой, показываем и шлём min.
 */
export function pickParams(settings: UniqSettings): Record<UniqKey, UniqParam> {
  return Object.fromEntries(
    UNIQ_KEYS.map((k) => {
      const p = { ...settings[k] }
      if (p.locked) p.max = p.min
      return [k, p]
    }),
  ) as Record<UniqKey, UniqParam>
}

/**
 * Подпись того, от чего зависит превью: папки, мастер и включённые границы.
 * Сам по себе замок картинку не меняет — в подпись не входит.
 */
export function previewSignature(folders: string[], settings: UniqSettings): string {
  return JSON.stringify([
    folders,
    settings.enabled,
    UNIQ_KEYS.map((k) => [settings[k].enabled, settings[k].min, settings[k].max]),
  ])
}
