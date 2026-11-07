import { useEffect, useMemo } from "react"
import { create } from "zustand"

import { ensureCampaignForm, saveCampaignForm } from "@/api/campaign"
import type { CampaignForm } from "@/api/types"
import { useAutosave } from "@/hooks/use-autosave"
import { notify } from "@/lib/notify"

import { fromServer, toServerForm, type FormValues } from "./form-model"
import { TOAST } from "./labels"

/* Одна форма публикации на приложение. Источник правды — сервер: форма
   приходит оттуда один раз, дальше правки уходят туда автосохранением. Запуск
   с другого экрана берёт ту же форму, подгружая её при первом обращении. */

interface FormStore {
  /** null — с сервера ещё не пришла */
  values: FormValues | null
  /** что уже лежит на сервере: пришло оттуда или записано туда */
  saved: CampaignForm | null
  /** была попытка запуска с ошибками — показываем их у полей */
  showErrors: boolean
  /** экрану публикации поставить фокус на первое ошибочное поле */
  pendingFocus: boolean
}

export const useFormStore = create<FormStore>(() => ({
  values: null,
  saved: null,
  showErrors: false,
  pendingFocus: false,
}))

export function updateForm(patch: Partial<FormValues>) {
  useFormStore.setState(({ values }) => (values ? { values: { ...values, ...patch } } : {}))
}

/** Форма с сервера — только первый раз: дальше правки главнее. */
export function hydrateForm(form: CampaignForm) {
  if (useFormStore.getState().values) return
  const values = fromServer(form)
  useFormStore.setState({ values, saved: toServerForm(values) })
}

export async function ensureFormValues(): Promise<FormValues> {
  const current = useFormStore.getState().values
  if (current) return current
  hydrateForm(await ensureCampaignForm())
  return useFormStore.getState().values!
}

async function saveForm(body: CampaignForm | null) {
  if (!body) return
  await saveCampaignForm(body)
  useFormStore.setState({ saved: body })
}

const onSaveError = (error: unknown) => notify.error(error, TOAST.notSaved)

/** Автосохранение формы на экранах «Креативы» и «Публикация». */
export function useFormAutosave() {
  const values = useFormStore((s) => s.values)
  const body = useMemo(() => (values ? toServerForm(values) : null), [values])
  const { markSaved } = useAutosave(body, saveForm, {
    delay: 500,
    enabled: body !== null,
    onError: onSaveError,
  })
  const loaded = values !== null
  // только что пришедшее с сервера (или записанное с прошлого захода на
  // экран) назад не отправляем
  useEffect(() => {
    const { saved } = useFormStore.getState()
    if (loaded && saved) markSaved(saved)
  }, [loaded, markSaved])
}
