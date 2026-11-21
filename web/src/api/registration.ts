import { api, LONG_TIMEOUT } from "./client"
export interface RegistrationMode {
  mode: 1 | 2 | 3 | 4
  supported: boolean
  available: boolean
  reason?: string
  local_only?: boolean
}
export interface RegistrationCapabilities {
  modes: RegistrationMode[]
  unavailable?: boolean
  geo_policy?: string
}
export interface RegistrationStatus {
  status:
    | "idle"
    | "queued"
    | "running"
    | "complete"
    | "failed"
    | "cancelled"
    | "dispatch_unknown"
    | "interrupted_or_unknown"
  job_id?: string
  scope?: string
  email_domain?: string
  username?: string
  account_saved?: boolean
  reason?: string
  server_reason?: string
  billing_status?: "unknown"
  username_selection?: {
    requested: string | null
    status: string
    reason: string
  }
}
export interface RegistrationInput {
  mode: 3 | 4
  expected_scope?: string
  proxy?: string
  anymessage_token: string
  country?: string
  age_min: number
  age_max: number
  domains: string[]
}
export const registrationCapabilities = () =>
  api.get<RegistrationCapabilities>("api/registration/capabilities")
export const registrationStatus = () =>
  api.get<RegistrationStatus>("api/registration")
export const startRegistration = (input: RegistrationInput) =>
  api.post<RegistrationStatus>("api/registration", input, {
    timeout: LONG_TIMEOUT,
  })
export const cancelRegistration = () =>
  api.post<RegistrationStatus>("api/registration/cancel")

export const registrationHistory = () =>
  api.get<{ results: RegistrationStatus[] }>("api/registration/history")
