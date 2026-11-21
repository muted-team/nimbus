import type {
  ProfileChanges,
  ProfileResult,
  ProfileStep,
} from "@/api/profile-edit"
export function profileOutcome(
  result: ProfileResult,
  requested: ProfileChanges,
  uid: string
): string {
  if (["blocked", "rejected", "unknown"].includes(result.verdict))
    return result.verdict
  const confirmed = Array.isArray(result.confirmed_fields)
    ? result.confirmed_fields
    : []
  if (result.verdict === "noop") {
    if (result.before?.user_id !== uid || requested.avatar_data)
      return "unknown"
    if (
      requested.nickname !== undefined &&
      result.before.nickname !== requested.nickname
    )
      return "unknown"
    if (
      requested.unique_id !== undefined &&
      result.before.unique_id !== requested.unique_id.toLowerCase()
    )
      return "unknown"
    return "noop"
  }
  if (
    typeof result.after?.nickname !== "string" ||
    typeof result.after?.unique_id !== "string"
  )
    return "unknown"
  if (result.verdict === "partial") {
    if (
      !confirmed.length ||
      result.before?.user_id !== uid ||
      result.after?.user_id !== uid
    )
      return "unknown"
    const relevant = (
      Object.keys(requested) as (keyof ProfileChanges)[]
    ).filter((field) => confirmed.includes(field))
    if (!relevant.length) return "unknown"
    if (
      relevant.includes("nickname") &&
      result.after.nickname !== requested.nickname
    )
      return "unknown"
    if (
      relevant.includes("unique_id") &&
      result.after.unique_id !== requested.unique_id?.toLowerCase()
    )
      return "unknown"
    return "partial"
  }
  if (
    result.verdict !== "confirmed" ||
    result.platform_verified !== true ||
    result.before?.user_id !== uid ||
    result.after?.user_id !== uid
  )
    return "unknown"
  for (const field of Object.keys(requested) as (keyof ProfileChanges)[]) {
    if (!confirmed.includes(field)) return "unknown"
    if (field === "nickname" && result.after.nickname !== requested.nickname)
      return "unknown"
    if (
      field === "unique_id" &&
      result.after.unique_id !== requested.unique_id?.toLowerCase()
    )
      return "unknown"
    if (
      field === "avatar_data" &&
      (typeof result.after.avatar_uri !== "string" || !result.after.avatar_uri)
    )
      return "unknown"
  }
  return "confirmed"
}
export const profileNeedsReadback = (
  result: ProfileResult,
  outcome?: string
): boolean =>
  outcome === "unknown" ||
  result.verdict === "unknown" ||
  result.state_saved === false ||
  !!(
    Array.isArray(result.steps) &&
    result.steps.some((step) => step?.verdict === "unknown")
  )
export function usernameStepText(step: ProfileStep): string {
  const messages: Record<string, string> = {
    available: "Имя пользователя доступно; изменение ещё не подтверждено",
    unavailable: "Имя пользователя занято или недоступно",
    platform_rejected: "TikTok отклонил изменение имени пользователя",
    challenge: "TikTok требует дополнительную проверку",
    http_error: "TikTok не подтвердил ответ на проверку имени",
    invalid_response: "Получен неполный ответ проверки имени",
    transport_error: "Ответ не получен; результат неизвестен",
    preparation_failed: "Запрос изменения не отправлен",
    unconfirmed_result: "Изменение имени пользователя не подтверждено",
    readback_mismatch: "Повторное чтение не подтвердило новое имя",
    readback_confirmed: "Новое имя подтверждено повторным чтением",
  }
  return (
    messages[step.reason ?? ""] ??
    step.message ??
    "Результат имени пользователя требует проверки"
  )
}
