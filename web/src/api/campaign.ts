import { useQuery } from "@tanstack/react-query"

import { api } from "./client"
import { keys, queryClient } from "./query-client"
import type { CampaignForm, CampaignStartBody, CampaignStatus } from "./types"

export function useCampaignStatus() {
  return useQuery({
    queryKey: keys.campaignStatus,
    queryFn: () => api.get<CampaignStatus>("api/campaign/status"),
    // основной путь — живой поток; опрос раз в 20 с подхватит публикацию,
    // запущенную из другого окна, если поток оборвался
    refetchInterval: 20_000,
  })
}

export const setCampaignStatus = (status: CampaignStatus) =>
  queryClient.setQueryData(keys.campaignStatus, status)

/** Публикация активна: идёт круг, останавливается или ждёт следующий круг. */
export function isCampaignLive(st: CampaignStatus | null | undefined): boolean {
  return !!st && (st.status === "running" || st.status === "stopping" || st.status === "waiting")
}

const fetchCampaignForm = () => api.get<CampaignForm>("api/campaign/form")

export function useCampaignForm() {
  return useQuery({
    queryKey: keys.campaignForm,
    queryFn: fetchCampaignForm,
    staleTime: Infinity,
  })
}

/** Форма вне React: запуск с экрана аккаунтов проверяет её, даже если экран
    публикации ещё не открывали. Кэш тот же, что у useCampaignForm. */
export const ensureCampaignForm = () =>
  queryClient.ensureQueryData({ queryKey: keys.campaignForm, queryFn: fetchCampaignForm })

export async function saveCampaignForm(form: CampaignForm) {
  const res = await api.put<CampaignForm>("api/campaign/form", form)
  queryClient.setQueryData(keys.campaignForm, res)
  return res
}

export async function startCampaign(body: CampaignStartBody) {
  const res = await api.post<{ ok: boolean; status?: CampaignStatus }>("api/campaign/start", body)
  if (res.status) setCampaignStatus(res.status)
  return res
}

export async function stopCampaign() {
  const status = await api.post<CampaignStatus>("api/campaign/stop", {})
  setCampaignStatus(status)
  return status
}
