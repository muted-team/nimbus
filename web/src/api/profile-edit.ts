import { api, LONG_TIMEOUT } from "./client"
export interface ProfileValues {
  user_id: string
  nickname: string
  unique_id: string
  avatar_uri?: string
}
export interface ProfileStep {
  step: string
  verdict: string
  reason?: string
  message?: string
  code?: number
}
export interface ProfileChanges {
  nickname?: string
  unique_id?: string
  avatar_data?: string
}
export interface ProfileResult {
  verdict: string
  message?: string
  error?: string
  before?: ProfileValues
  after?: ProfileValues | null
  confirmed_fields?: string[]
  changed_fields?: string[]
  steps?: ProfileStep[]
  platform_verified?: boolean
  state_saved?: boolean
  state_error?: string
  stop_account?: boolean
}
export interface ProfilePolicy {
  cooldown_days?: number
  next_change_at?: number | null
  changeable?: boolean | null
  native_supported?: boolean
}
export interface ProfileInfo {
  verdict: string
  before: ProfileValues
  policies: Record<string, ProfilePolicy>
  last_result?: ProfileResult
  last_requested?: ProfileChanges
  last_expected_uid?: string
}
export const readTikTokProfile = (username: string) =>
  api.post<ProfileInfo>(
    "api/tiktok-profile/info",
    { username },
    { timeout: LONG_TIMEOUT }
  )
export const updateTikTokProfile = (
  username: string,
  changes: ProfileChanges,
  expected_user_id: string,
  acknowledge_cooldown: boolean
) =>
  api.post<ProfileResult>(
    "api/tiktok-profile/update",
    { username, changes, expected_user_id, acknowledge_cooldown },
    { timeout: LONG_TIMEOUT }
  )
