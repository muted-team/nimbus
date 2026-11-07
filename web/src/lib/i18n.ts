import { useSyncExternalStore } from "react"

import { messages } from "./translations"

export type Language = "en" | "ru" | "uk"
export const LANGUAGE_STORAGE_KEY = "ttwa.language"

export function readLanguage(value: string | null): Language {
  return value === "en" || value === "uk" ? value : "ru"
}

function savedLanguage(): Language {
  if (typeof window === "undefined") return "ru"
  try { return readLanguage(globalThis.localStorage?.getItem(LANGUAGE_STORAGE_KEY)) }
  catch { return "ru" }
}

let language = savedLanguage()
const listeners = new Set<() => void>()
export const getLanguage = () => language
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function updateDocument() {
  if (typeof document !== "undefined") document.documentElement.lang = language
}
updateDocument()

export function setLanguage(next: Language): void {
  if (next !== "ru" && next !== "en" && next !== "uk") return
  if (typeof window !== "undefined") {
    try { window.localStorage?.setItem(LANGUAGE_STORAGE_KEY, next) } catch { /* private browser */ }
  }
  if (next === language) return
  language = next
  updateDocument()
  listeners.forEach((listener) => listener())
}

if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key !== LANGUAGE_STORAGE_KEY && event.key !== null) return
    const next = event.key === null ? "ru" : readLanguage(event.newValue)
    if (next === language) return
    language = next
    updateDocument()
    listeners.forEach((listener) => listener())
  })
}

/** Subscribe without remounting screens, so changing language retains form drafts. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, getLanguage, () => "ru")
}

/** Interpolation keeps user names and server diagnostics separate from catalog text. */
export function t(source: string, values: readonly unknown[] = []): string {
  const template = language === "ru" ? source : messages[source]?.[language] ?? source
  return template.replace(/\{(\d+)\}/g, (match, index: string) =>
    Number(index) < values.length ? String(values[Number(index)]) : match)
}

const localized = new WeakMap<object, object>()

/** Label objects retain source strings and resolve the active language on every read. */
export function localize<T extends object>(value: T): T {
  const cached = localized.get(value)
  if (cached) return cached as T
  const result = new Proxy(value, {
    get(target, key, receiver) {
      const item: unknown = Reflect.get(target, key, receiver)
      if (typeof item === "string") return t(item)
      if (typeof item === "object" && item !== null) return localize(item)
      return item
    },
  })
  localized.set(value, result)
  return result
}

export function languageChoices() {
  // Stable alphabetical order in the current interface language.
  return [
    { value: "en" as const, label: t("Английский") },
    { value: "ru" as const, label: t("Русский") },
    { value: "uk" as const, label: t("Украинский") },
  ]
}
