import { t, useLanguage } from "@/lib/i18n"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/* Числовое поле. type="text" + inputmode, а не type="number": number отдаёт
   пустую строку, пока набранное не дочитано, и «1,» посреди набора стало бы
   нулём. Значение — строка как набрано; разбирает вызывающий (parseNumber). */

interface NumberInputProps extends Omit<React.ComponentProps<typeof Input>, "value" | "onChange" | "type"> {
  value: string
  onValueChange: (value: string) => void
  /** разрешить дробную часть (запятая или точка) */
  decimal?: boolean
  /** разрешить минус */
  signed?: boolean
}

export function NumberInput({ value, onValueChange, decimal, signed, className, ...props }: NumberInputProps) {
  const allowed = new RegExp(`[^0-9${decimal ? ",." : ""}${signed ? "\\-−" : ""}]`, "g")
  return (
    <Input
      type="text"
      inputMode={decimal ? "decimal" : "numeric"}
      autoComplete="off"
      spellCheck={false}
      value={value}
      onChange={(e) => onValueChange(e.target.value.replace(allowed, ""))}
      className={cn("tabular", className)}
      {...props}
    />
  )
}

/** "1,5" -> 1.5; пусто -> fallback; мусор -> null (ошибка ввода). */
export function parseNumber(raw: string, fallback: number | null = null): number | null {
  const t = raw.replace(/\s/g, "").replace(",", ".").replace("−", "-")
  if (!t) return fallback
  if (!/^-?\d*(\.\d*)?$/.test(t) || t === "-" || t === ".") return null
  return Number(t)
}

/** Пара «от — до» в одну строку. */
export function RangeInput({
  min,
  max,
  onMinChange,
  onMaxChange,
  decimal,
  signed,
  invalid,
  disabled,
  label,
  className,
  inputClassName,
  "aria-describedby": describedBy,
  placeholder = [t("от"), t("до")],
  field,
}: {
  min: string
  max: string
  onMinChange: (value: string) => void
  onMaxChange: (value: string) => void
  decimal?: boolean
  signed?: boolean
  invalid?: boolean
  disabled?: boolean
  /** для доступного имени полей: «Пауза» -> «Пауза, от» */
  label: string
  className?: string
  inputClassName?: string
  "aria-describedby"?: string
  placeholder?: [string, string]
  /** data-field первого поля — перевод фокуса на ошибку */
  field?: string
}) {
  useLanguage()
  const common = {
    decimal,
    signed,
    disabled,
    "aria-invalid": invalid || undefined,
    "aria-describedby": describedBy,
    className: inputClassName,
  }
  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <NumberInput
        {...common}
        value={min}
        onValueChange={onMinChange}
        placeholder={placeholder[0]}
        aria-label={t("{0}, от", [label])}
        data-field={field}
      />
      <span className="shrink-0 text-muted-foreground" aria-hidden>
        –
      </span>
      <NumberInput
        {...common}
        value={max}
        onValueChange={onMaxChange}
        placeholder={placeholder[1]}
        aria-label={t("{0}, до", [label])}
      />
    </div>
  )
}
