import type {
  RegistrationCapabilities,
  RegistrationStatus,
} from "@/api/registration"
export const registrationBusy = (job: RegistrationStatus): boolean =>
  !["idle", "complete", "failed", "cancelled"].includes(job.status)
export const registrationPolling = (job: RegistrationStatus): boolean =>
  ["queued", "running"].includes(job.status)
export const modeAvailable = (
  caps: RegistrationCapabilities | null,
  mode: 3 | 4
): boolean =>
  !!caps?.modes.some(
    (row) =>
      row.mode === mode && row.supported === true && row.available === true
  )
