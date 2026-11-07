import { t, useLanguage } from "@/lib/i18n"
import { SearchIcon, XIcon } from "lucide-react"
import { useRef } from "react"

import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group"
import { useHotkey } from "@/hooks/use-hotkey"
import { cn } from "@/lib/utils"

/* Поиск по списку: Ctrl+F (или /) ставит фокус, Esc очищает и уходит из поля.
   Один на экран — горячая клавиша глобальная, пока экран открыт. */
export function SearchInput({
  value,
  onValueChange,
  placeholder = t("Поиск"),
  className,
}: {
  value: string
  onValueChange: (value: string) => void
  placeholder?: string
  className?: string
}) {
  useLanguage()
  const ref = useRef<HTMLInputElement>(null)
  useHotkey(["Mod+F", "/"], () => {
    ref.current?.focus()
    ref.current?.select()
  })

  return (
    <InputGroup className={cn("w-full sm:w-64", className)}>
      <InputGroupAddon>
        <SearchIcon />
      </InputGroupAddon>
      <InputGroupInput
        ref={ref}
        type="search"
        value={value}
        placeholder={placeholder}
        aria-label={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onValueChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            if (value) onValueChange("")
            else ref.current?.blur()
            e.preventDefault()
          }
        }}
        className="[&::-webkit-search-cancel-button]:hidden"
      />
      {value ? (
        <InputGroupAddon align="inline-end">
          <InputGroupButton size="icon-xs" aria-label={t("Очистить")} onClick={() => onValueChange("")}>
            <XIcon />
          </InputGroupButton>
        </InputGroupAddon>
      ) : null}
    </InputGroup>
  )
}
