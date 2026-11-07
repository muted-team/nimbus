import { afterEach, describe, expect, it } from "vitest"

import { getLanguage, languageChoices, localize, readLanguage, setLanguage, t } from "./i18n"
import { count, fmtDec, fmtSpan } from "./format"
import { REPEAT_UNIT_ITEMS } from "@/features/campaign/labels"

afterEach(() => setLanguage("ru"))

describe("interface language", () => {
  it("defaults to Russian and ignores unsupported saved values", () => {
    expect(readLanguage(null)).toBe("ru")
    expect(readLanguage("de")).toBe("ru")
    expect(readLanguage("uk")).toBe("uk")
    expect(languageChoices().map((item) => item.value)).toEqual(["en", "ru", "uk"])
  })

  it("changes existing label objects and interpolated messages without rebuilding them", () => {
    const labels = localize({ title: "Настройки", nested: [{ title: "Аккаунты" }] })
    setLanguage("en")
    expect(getLanguage()).toBe("en")
    expect(labels.title).toBe("Settings")
    expect(labels.nested[0].title).toBe("Accounts")
    expect(t("Изменить {0}", ["user.Кате"])).toBe("Edit user.Кате")
    setLanguage("uk")
    expect(labels.title).toBe("Налаштування")
    expect(t("Изменить {0}", ["user.Кате"])).toBe("Змінити user.Кате")
  })

  it("keeps account names, protocol values, and unknown diagnostic text intact", () => {
    setLanguage("en")
    expect(t("user.Кате")).toBe("user.Кате")
    expect(t("Chrome 152")).toBe("Chrome 152")
    expect(t("raw diagnostic 10221")).toBe("raw diagnostic 10221")
  })

  it("uses English plural forms and Ukrainian Slavic plural forms", () => {
    setLanguage("en")
    expect(t("аккаунт")).toBe("account")
    expect(t("аккаунта")).toBe("accounts")
    setLanguage("uk")
    expect(t("аккаунтов")).toBe("акаунтів")
    expect(count(3, ["аккаунт", "аккаунта", "аккаунтов"])).toBe("3 акаунти")
    expect(count(11, ["аккаунт", "аккаунта", "аккаунтов"])).toBe("11 акаунтів")
    setLanguage("en")
    expect(count(21, ["аккаунт", "аккаунта", "аккаунтов"])).toBe("21 accounts")
    expect(fmtDec(12.5)).toBe("12.50")
    expect(fmtSpan(125000)).toBe("2 min")
    expect(REPEAT_UNIT_ITEMS[0].label).toBe("minutes")
    setLanguage("uk")
    expect(REPEAT_UNIT_ITEMS[0].label).toBe("хвилин")
  })
})
