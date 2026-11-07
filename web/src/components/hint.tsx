import { isValidElement, type ReactElement, type ReactNode } from "react"
import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { hotkeyKeys } from "@/hooks/use-hotkey"
import { cn } from "@/lib/utils"

/* Подсказка над элементом: только название и клавиша, без описаний —
   «Обновить», «Запустить Ctrl ⏎». Серая кнопка в подсказке говорит, почему
   она серая (reason): у выключенной кнопки нет событий мыши, поэтому такую
   оборачиваем в span — наводится он, а не кнопка. */

export function Hint({
  label,
  hotkey,
  reason,
  side,
  className,
  children,
}: {
  label: ReactNode
  /** сочетание в формате useHotkey: "Mod+Enter" */
  hotkey?: string
  /** почему недоступно — показывается вместо названия у выключенной кнопки */
  reason?: ReactNode
  side?: "top" | "bottom" | "left" | "right"
  /** вид обёртки у выключенной кнопки: у растянутой кнопки она тоже тянется */
  className?: string
  children: ReactElement
}) {
  const disabled = isValidElement<{ disabled?: boolean }>(children) && !!children.props.disabled
  const text = disabled && reason ? reason : label
  return (
    <Tooltip>
      <TooltipTrigger
        render={disabled ? <span className={cn("inline-flex", className)} tabIndex={reason ? 0 : undefined} /> : children}
      >
        {disabled ? children : undefined}
      </TooltipTrigger>
      <TooltipContent side={side}>
        {text}
        {hotkey && !(disabled && reason) ? (
          <KbdGroup>
            {hotkeyKeys(hotkey).map((k) => (
              <Kbd key={k}>{k}</Kbd>
            ))}
          </KbdGroup>
        ) : null}
      </TooltipContent>
    </Tooltip>
  )
}

/** Кнопка-значок: название уходит и в подсказку, и в aria-label. */
export function IconButton({
  label,
  icon: Icon,
  hotkey,
  reason,
  side,
  variant = "ghost",
  size = "icon",
  className,
  ...props
}: Omit<React.ComponentProps<typeof Button>, "children" | "aria-label"> & {
  label: string
  icon: LucideIcon | (() => ReactNode)
  hotkey?: string
  reason?: ReactNode
  side?: "top" | "bottom" | "left" | "right"
}) {
  return (
    <Hint label={label} hotkey={hotkey} reason={reason} side={side}>
      <Button variant={variant} size={size} aria-label={label} className={className} {...props}>
        <Icon />
      </Button>
    </Hint>
  )
}
