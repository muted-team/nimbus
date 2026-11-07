import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox"
import { CheckIcon, MinusIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/* Флажок — выбор строк в таблицах. Отмеченный — акцентом: выделение — одно
   из двух мест, где акцентный цвет уместен. indeterminate — «выбрана часть»,
   у флажка в шапке таблицы. after:-inset — палец попадает мимо 16 px. */

function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer relative flex size-4 shrink-0 items-center justify-center rounded-sm border border-input bg-input/30 transition-colors outline-none",
        "after:absolute after:-inset-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50 data-disabled:cursor-not-allowed data-disabled:opacity-50",
        "data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground",
        "data-indeterminate:border-primary data-indeterminate:bg-primary data-indeterminate:text-primary-foreground",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="group/indicator grid place-content-center text-current [&>svg]:size-3"
      >
        <CheckIcon className="group-data-indeterminate/indicator:hidden" strokeWidth={3} />
        <MinusIcon className="hidden group-data-indeterminate/indicator:block" strokeWidth={3} />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
