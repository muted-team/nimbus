import { localize } from "@/lib/i18n"
import {
  ContrastIcon,
  ImageIcon,
  PaletteIcon,
  RainbowIcon,
  RotateCwIcon,
  SplineIcon,
  SunIcon,
  ZoomInIcon,
  type LucideIcon,
} from "lucide-react"

import type { UniqKey } from "@/api/types"
import { fmtDec, fmtInt, fmtSigned } from "@/lib/format"

/* Подписи и константы уникализатора в одном месте: строка параметра и
   применённые значения в превью берут подпись и формат отсюда. Тексты пустого
   превью живут рядом со своим состоянием — в preview-model.ts. Порядок — как
   на экране. */

export const UNIQ_LABELS: Record<UniqKey, { label: string; icon: LucideIcon }> = localize({
  rotate: { label: "Поворот, °", icon: RotateCwIcon },
  scale: { label: "Масштаб, %", icon: ZoomInIcon },
  compress: { label: "Сжатие, %", icon: ImageIcon },
  brightness: { label: "Яркость, %", icon: SunIcon },
  contrast: { label: "Контраст, %", icon: ContrastIcon },
  saturation: { label: "Насыщенность, %", icon: PaletteIcon },
  gamma: { label: "Гамма", icon: SplineIcon },
  hue: { label: "Цвет, °", icon: RainbowIcon },
})

/** Применённое к фото значение: сдвиги — со знаком, гамма — с копейками. */
export const APPLIED_FORMAT: Record<UniqKey, (n: number) => string> = {
  rotate: fmtSigned,
  scale: fmtInt,
  compress: fmtInt,
  brightness: fmtInt,
  contrast: fmtInt,
  saturation: fmtInt,
  gamma: fmtDec,
  hue: fmtSigned,
}

export const TOAST = localize({
  notSaved: "Не удалось сохранить уникализатор",
} as const)

/** Вкладка в «Креативах» и шаг «Обработка» в публикации — одно название. */
export const UNIQ_TITLE = "Уникализация"
