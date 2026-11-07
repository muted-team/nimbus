import { SimpleSelect } from "@/components/simple-select"
import { getLanguage, languageChoices, setLanguage, t, useLanguage, type Language } from "@/lib/i18n"

import { SettingRow, SettingsGroup } from "./settings-row"

export function LanguagePanel() {
  useLanguage()
  return (
    <SettingsGroup title={t("Язык интерфейса")}>
      <SettingRow label={t("Язык")}>
        <SimpleSelect
          aria-label={t("Язык интерфейса")}
          value={getLanguage()}
          items={languageChoices()}
          onValueChange={(value) => setLanguage(value as Language)}
        />
      </SettingRow>
    </SettingsGroup>
  )
}
