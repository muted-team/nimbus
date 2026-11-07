import type { BulkAddResponse } from "@/api/types"
import { remainingLineDraft } from "@/lib/line-draft"

export function submissionText(value: string, whole: boolean): string | null {
  if (/^\s*[[{]/.test(value)) {
    if (!whole) {
      try { JSON.parse(value) } catch { return null }
    }
    return value
  }
  return value.slice(0, whole ? value.length : value.lastIndexOf("\n") + 1)
}

export function remainingDraft(
  sent: string,
  latest: string,
  errors: BulkAddResponse["errors"]
): { text: string; errors: BulkAddResponse["errors"]; retained: string } {
  if (/^\s*[[{]/.test(sent)) {
    if (latest !== sent) return { text: latest, errors: [], retained: "" }
    return errors.length ? { text: latest, errors, retained: sent } : { text: "", errors: [], retained: "" }
  }
  return remainingLineDraft(sent, latest, errors)
}
