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

interface SimpleSelectProps<V extends string> extends Pick<ComponentProps<typeof SelectTrigger>, "size"> {
  value: V
  items: readonly { value: V; label: string }[]
  onValueChange: (value: V) => void
  className?: string
  "aria-label"?: string
}

export function SimpleSelect<V extends string>({
  value,
  items,
  onValueChange,
  className,
  ...props
}: SimpleSelectProps<V>) {
  return (
    <Select
      items={items}
      value={value}
      onValueChange={(next) => {
        if (next !== null) onValueChange(next)
      }}
    >
      <SelectTrigger className={className} {...props}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}
