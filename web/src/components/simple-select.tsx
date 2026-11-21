import type { ComponentProps } from "react"

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

/* Выпадающий список из готовых пунктов: label выбранного значения показывает
   сам (items на корне), null в onValueChange не отдаём наружу. */

interface SimpleSelectProps<V extends string> extends Pick<
  ComponentProps<typeof SelectTrigger>,
  "size" | "disabled"
> {
  value: V
  items: readonly {
    value: V
    label: string
    disabled?: boolean
    reason?: string
  }[]
  onValueChange: (value: V) => void
  className?: string
  "aria-label"?: string
}

export function SimpleSelect<V extends string>({
  value,
  items,
  onValueChange,
  className,
  disabled,
  ...props
}: SimpleSelectProps<V>) {
  return (
    <Select
      items={items}
      disabled={disabled}
      value={value}
      onValueChange={(next) => {
        if (next !== null) onValueChange(next)
      }}
    >
      <SelectTrigger className={className} disabled={disabled} {...props}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem
              key={item.value}
              value={item.value}
              disabled={item.disabled}
              title={item.reason}
            >
              <span className="flex flex-col">
                <span>{item.label}</span>
                {item.reason ? (
                  <span className="text-xs text-muted-foreground">
                    {item.reason}
                  </span>
                ) : null}
              </span>
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
