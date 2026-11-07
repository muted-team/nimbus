import { localize, t, useLanguage } from "@/lib/i18n"
import { setTheme, useTheme, type ThemeMode } from "@/app/theme"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

import { SettingRow, SettingsGroup } from "./settings-row"

const OPTIONS = localize([
  { value: "system", label: "Системная" },
  { value: "light", label: "Светлая" },
  { value: "dark", label: "Тёмная" },
] as const)

export function ThemePanel() {
  useLanguage()
  const { mode } = useTheme()
  return (
    <SettingsGroup title={t("Внешний вид")}>
      <SettingRow label={t("Тема")}>
        <ToggleGroup
          value={[mode]}
          aria-label={t("Тема")}
          onValueChange={(values) => {
            const next = values[0] as ThemeMode | undefined
            if (next) setTheme(next)
          }}
        >
          {OPTIONS.map((option) => (
            <ToggleGroupItem key={option.value} value={option.value}>
              {option.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </SettingRow>
    </SettingsGroup>
  )
}
